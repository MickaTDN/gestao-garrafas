using System.Diagnostics;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.ServiceProcess;
using System.Text.Json;

namespace GVA;

static class Program
{
    internal static JsonElement Trust = JsonDocument.Parse(ReadTrust()).RootElement;
    internal static string Channel => Trust.GetProperty("channel").GetString()!;
    internal static string Root => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), Channel == "synthetic" ? "GestaoVertenteAveludada-Teste" : "GestaoVertenteAveludada");
    internal static JsonElement State => JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "installation.json"))).RootElement;
    internal static string Release => State.GetProperty("release").GetString()!;
    static string ReadTrust() { using var stream = Assembly.GetExecutingAssembly().GetManifestResourceStream("release-trust.json")!; using var reader = new StreamReader(stream); return reader.ReadToEnd(); }

    [STAThread]
    static int Main(string[] args)
    {
        if (args.Length == 2 && args[0] == "--verify-signer")
        {
            try { Authenticode.Verify(args[1], Trust.GetProperty("authenticode_sha256").GetString()!); return 0; }
            catch { return 1; }
        }
        if (args.Length == 2 && args[0] == "--service")
        { ServiceBase.Run(new NativeService(args[1])); return 0; }
        ApplicationConfiguration.Initialize();
        try
        {
            if (args.Length == 3 && args[0] == "--ci-wizard")
            {
                if (Channel != "synthetic") throw new UserError("Apenas validação sintética na CI.");
                var requestData = JsonDocument.Parse(File.ReadAllText(args[2])).RootElement;
                string action = requestData.TryGetProperty("archive", out _) ? "recover" : File.Exists(Path.Combine(Root, "installation.json")) ? "update" : "install";
                return Run(Path.Combine(args[1], "payload"), action, args[2], args[1]);
            }
            if (args.Length == 3 && args[0] == "--preflight") { Preflight(args[1], args[2]); return 0; }
            if (args.Length == 1 && args[0] == "--maintenance") { Maintenance(); return 0; }
            if (args.Length == 2 && args[0] == "--wizard") return Wizard(args[1]);
            if (args.Length == 1 && args[0] == "--uninstall") return Run(Release, "uninstall");
            Application.Run(new Dashboard()); return 0;
        }
        catch (Exception error)
        { if (Channel == "synthetic") { string log = Environment.GetEnvironmentVariable("RUNNER_TEMP") is string ci ? Path.Combine(ci, "gva-native") : Path.GetTempPath(); File.WriteAllText(Path.Combine(log, "host-error.txt"), error is UserError ? error.Message : error.GetType().Name); return 1; }
          MessageBox.Show("Não foi possível concluir a operação. Preserve os dados e contacte a informática.\n" + (error is UserError ? error.Message : error.GetType().Name), "Gestão Vertente Aveludada", MessageBoxButtons.OK, MessageBoxIcon.Error); return 1; }
    }

    [StructLayout(LayoutKind.Sequential)] sealed class MemoryStatus { public uint length = (uint)Marshal.SizeOf<MemoryStatus>(); public uint load; public ulong totalPhysical, availablePhysical, totalPage, availablePage, totalVirtual, availableVirtual, availableExtended; }
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] static extern bool GlobalMemoryStatusEx([In, Out] MemoryStatus status);
    [DllImport("kernel32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] static extern bool GetPhysicallyInstalledSystemMemory(out ulong kilobytes);

    static void Preflight(string manifestPath, string installer)
    {
        var anchor = File.Exists(Path.Combine(Root, "package-policy.json")) ? JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "package-policy.json"))).RootElement : Trust;
        if (Channel == "release") Authenticode.Verify(installer, anchor.GetProperty("authenticode_sha256").GetString()!);
        if (Channel == "release")
        {
            var memory = new MemoryStatus();
            if (!(GetPhysicallyInstalledSystemMemory(out ulong installedKB) ? installedKB >= 16UL * 1024 * 1024 : GlobalMemoryStatusEx(memory) && memory.totalPhysical >= 14UL * 1024 * 1024 * 1024)) throw new UserError("É necessário um computador com pelo menos 16 GB de RAM.");
            if (new DriveInfo(Path.GetPathRoot(Root)!).AvailableFreeSpace < 8L * 1024 * 1024 * 1024) throw new UserError("Espaço livre insuficiente. A informática deve reservar espaço para dados, cópias e restauro.");
        }
        byte[] raw = File.ReadAllBytes(manifestPath);
        using var key = ECDsa.Create(); key.ImportFromPem(anchor.GetProperty("public_key").GetString()!);
        byte[] context = System.Text.Encoding.UTF8.GetBytes("gva-windows-package-v1\0");
        byte[] signed = context.Concat(raw).ToArray();
        byte[] sig = Convert.FromBase64String(File.ReadAllText(Path.ChangeExtension(manifestPath, ".sig")));
        if (!key.VerifyData(signed, sig, HashAlgorithmName.SHA256, DSASignatureFormat.Rfc3279DerSequence)) throw new UserError("Assinatura do pacote inválida.");
        var next = JsonDocument.Parse(raw).RootElement;
        if (next.GetProperty("channel").GetString() != Channel || next.GetProperty("postgres_major").GetInt32() != 17) throw new UserError("Pacote incompatível.");
        if (File.Exists(Path.Combine(Root, "installation.json")))
        {
            var old = Version.Parse(State.GetProperty("version").GetString()!);
            var incoming = Version.Parse(next.GetProperty("version").GetString()!);
            bool uninstalled = State.TryGetProperty("uninstalled", out var removed) && removed.GetBoolean();
            bool repair = uninstalled && old == incoming;
            if (repair && !State.GetProperty("package_sha256").GetString()!.Equals(Convert.ToHexString(SHA256.HashData(raw)), StringComparison.OrdinalIgnoreCase)) throw new UserError("Reponha o instalador exato da versão anterior.");
            if ((old >= incoming && !repair) || (uninstalled && !repair) || old < Version.Parse(next.GetProperty("minimum_version").GetString()!) || State.GetProperty("channel").GetString() != Channel) throw new UserError("Versão antiga, repetida ou incompatível. Após desinstalar, reponha primeiro a versão exata.");
            if (File.Exists(Path.Combine(Root, "maintenance.json"))) throw new UserError("Manutenção interrompida. É necessária recuperação pela informática.");
        }
    }

    static void Maintenance()
    {
        // Elevation is explicit, limited to maintenance, and uses the Windows UAC prompt.
        bool admin = new System.Security.Principal.WindowsPrincipal(System.Security.Principal.WindowsIdentity.GetCurrent()).IsInRole(System.Security.Principal.WindowsBuiltInRole.Administrator);
        if (!admin) { Process.Start(new ProcessStartInfo(Environment.ProcessPath!, "--maintenance") { UseShellExecute = true, Verb = "runas" }); return; }
        using var form = new Form { Text = "Manutenção — informática", Width = 580, Height = 380 };
        var layout = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, Padding = new Padding(20) }; form.Controls.Add(layout);
        layout.Controls.Add(new Label { Text = "Operações autorizadas de manutenção. A recuperação exige uma instalação isolada nova e a versão exata do backup.", Width = 510, Height = 60 });
        void Button(string label, Action action) { var b = new Button { Text = label, Width = 450, Height = 45 }; b.Click += async (_, _) => { b.Enabled = false; try { await Task.Run(action); MessageBox.Show("Operação concluída."); } catch (Exception e) { MessageBox.Show(e is UserError ? e.Message : "Falha; preserve os dados e contacte a informática."); } finally { b.Enabled = true; } }; layout.Controls.Add(b); }
        Button("Criar backup manual cifrado", () => Run(Release, "backup"));
        Button("Preparar publicador HTTPS (configuração aprovada)", () => {
            // File dialog must run on the STA UI thread.
            form.Invoke(() => { using var d = new OpenFileDialog { Filter = "Configuração aprovada|*.json" }; if (d.ShowDialog() == DialogResult.OK) Run(Release, "publisher", PrivateRequest(new { configuration = d.FileName })); });
        });
        Button("Ativar publicador após aprovação de rede", () => {
            form.Invoke(() => { if (MessageBox.Show("A informática confirmou DNS, HTTPS confiável, certificados por dispositivo, CRL e firewall restrita? Não criar encaminhamento de portas na Internet.", "Aprovação de rede", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) == DialogResult.Yes) Run(Release, "enable-publisher", PrivateRequest(new { it_network_ready = true })); });
        });
        Button("Aprovar recuperação após conferência (informática)", () => {
            form.Invoke(() => { if (MessageBox.Show("Confirmou a integridade, a sequência Android e TODAS as entradas exportadas após o backup? A origem anterior está isolada e parada? Esta ação autoriza o arranque local da cópia recuperada.", "Conferência obrigatória", MessageBoxButtons.YesNo, MessageBoxIcon.Warning) == DialogResult.Yes) Run(Release, "approve-recovery", PrivateRequest(new { confirmed_identity_history = true })); });
        });
        Button("Abrir instruções de recuperação e configuração", () => Process.Start(new ProcessStartInfo(Path.Combine(Release, "app", "docs", "windows-native.html")) { UseShellExecute = true }));
        form.ShowDialog();
    }

    internal static int Run(string release, string action, string? request = null, string? package = null)
    {
        string trust = Path.Combine(Path.GetTempPath(), "gva-trust-" + Guid.NewGuid() + ".json");
        File.WriteAllText(trust, ReadTrust()); // Public verification key only.
        try
        {
            var info = new ProcessStartInfo(Path.Combine(release, "python", "python.exe")) { WorkingDirectory = Path.Combine(release, "app"), UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true, RedirectStandardOutput = true };
            foreach (string arg in new[] { "-s", "-B", "-m", "native_windows.cli", action, "--trust", trust }) info.ArgumentList.Add(arg);
            if (request != null) { info.ArgumentList.Add("--request"); info.ArgumentList.Add(request); }
            if (package != null) { info.ArgumentList.Add("--package"); info.ArgumentList.Add(package); }
            info.Environment["GVA_NATIVE_CHANNEL"] = Channel;
            info.Environment["PYTHONUTF8"] = "1"; info.Environment["PYTHONIOENCODING"] = "utf-8";
            info.StandardErrorEncoding = System.Text.Encoding.UTF8; info.StandardOutputEncoding = System.Text.Encoding.UTF8;
            using var process = Process.Start(info)!;
            var output = process.StandardOutput.ReadToEndAsync();
            var errors = process.StandardError.ReadToEndAsync();
            process.WaitForExit();
            if (process.ExitCode != 0) throw new UserError(errors.GetAwaiter().GetResult().Trim());
            return 0;
        }
        finally { File.Delete(trust); if (request != null) File.Delete(request); }
    }

    static int Wizard(string package)
    {
        string release = Path.Combine(package, "payload");
        Run(release, "verify", package: package); // No service/data changes before verification.
        bool updating = File.Exists(Path.Combine(Root, "installation.json"));
        using var form = new Form { Text = updating ? "Atualizar Gestão Vertente Aveludada" : "Preparar Gestão Vertente Aveludada", Width = 600, Height = 540, StartPosition = FormStartPosition.CenterScreen, FormBorderStyle = FormBorderStyle.FixedDialog, MaximizeBox = false };
        var flow = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false, AutoScroll = true, Padding = new Padding(18) };
        form.Controls.Add(flow);
        var status = new Label { Dock = DockStyle.Fill, Text = "Preencha os dados e prepare a instalação.", AutoEllipsis = true };
        var progress = new ProgressBar { Dock = DockStyle.Bottom, Style = ProgressBarStyle.Marquee, Visible = false };
        var feedback = new Panel { Dock = DockStyle.Top, Height = 78, Padding = new Padding(12) };
        feedback.Controls.Add(status); feedback.Controls.Add(progress); form.Controls.Add(feedback); feedback.BringToFront();
        using var phaseTimer = new System.Windows.Forms.Timer { Interval = 500 };
        phaseTimer.Tick += (_, _) => status.Text = WizardOperation.Phase(Root);
        void Label(string text) => flow.Controls.Add(new Label { Text = text, Width = 535, Height = 40 });
        TextBox Field(string label, bool secret = false) { Label(label); var field = new TextBox { Width = 530, UseSystemPasswordChar = secret }; flow.Controls.Add(field); return field; }
        Label(updating ? "Será criado e restaurado um backup de ensaio antes das migrações. Se falhar, o arranque fica bloqueado para recuperação." : "Instala serviços privados PostgreSQL 17, aplicação e backups. Só a informática necessita de privilégios de administrador. Não abre portas da firewall.");
        var recovering = new CheckBox { Text = "Recuperar um backup numa instalação isolada NOVA", Width = 530 };
        if (!updating) flow.Controls.Add(recovering);
        var archive = updating ? null : Field("Ficheiro .gvabackup (apenas para recuperação)");
        if (!updating) { var chooseArchive = new Button { Text = "Escolher backup…", Width = 180 }; chooseArchive.Click += (_, _) => { using var d = new OpenFileDialog { Filter = "Backup cifrado|*.gvabackup" }; if (d.ShowDialog() == DialogResult.OK) archive!.Text = d.FileName; }; flow.Controls.Add(chooseArchive); }
        var user = updating ? null : Field("Nome da conta de administrador da aplicação");
        var password = updating ? null : Field("Palavra-passe da conta (mínimo 12 caracteres)", true);
        var confirm = updating ? null : Field("Confirmar palavra-passe", true);
        var key = Field(updating ? "Chave privada de recuperação (ficheiro guardado separadamente)" : "Novo ficheiro para a chave de recuperação num suporte empresarial autorizado");
        var browse = new Button { Text = "Escolher ficheiro…", Width = 180 };
        browse.Click += (_, _) => { if (updating || recovering.Checked) { using var d = new OpenFileDialog { Filter = "Chave de recuperação|*.pem" }; if (d.ShowDialog() == DialogResult.OK) key.Text = d.FileName; } else { using var d = new SaveFileDialog { Filter = "Chave de recuperação|*.pem", FileName = "GVA-recuperacao.pem", OverwritePrompt = true }; if (d.ShowDialog() == DialogResult.OK) key.Text = d.FileName; } };
        flow.Controls.Add(browse);
        var phrase = Field(updating ? "Frase da chave de recuperação" : "Nova frase de recuperação (mínimo 16 caracteres); guarde-a separadamente", true);
        var phraseConfirm = updating ? null : Field("Confirmar frase de recuperação", true);
        var demo = new CheckBox { Text = "Instalação com dados fictícios para validação", Checked = true, Enabled = Channel != "synthetic", Width = 530 }; if (!updating) flow.Controls.Add(demo);
        var ports = new FlowLayoutPanel { FlowDirection = FlowDirection.TopDown, Width = 530, Height = 120, Visible = false };
        var httpPort = new NumericUpDown { Minimum = 1024, Maximum = 65535, Value = 8765, Width = 150 };
        var dbPort = new NumericUpDown { Minimum = 1024, Maximum = 65535, Value = 55432, Width = 150 };
        if (!updating) {
            var advanced = new CheckBox { Text = "Portas locais alternativas (informática)", Width = 530 };
            advanced.CheckedChanged += (_, _) => ports.Visible = advanced.Checked;
            ports.Controls.Add(new Label { Text = "Aplicação — sempre apenas neste computador", Width = 500 }); ports.Controls.Add(httpPort);
            ports.Controls.Add(new Label { Text = "PostgreSQL — sempre apenas neste computador", Width = 500 }); ports.Controls.Add(dbPort);
            flow.Controls.Add(advanced); flow.Controls.Add(ports);
        }
        var button = new Button { Text = updating ? "Verificar backup e atualizar" : "Preparar instalação", Width = 260, Height = 40 };
        flow.Controls.Add(button);
        button.Click += async (_, _) => {
            if (!updating && !recovering.Checked && (password!.Text != confirm!.Text || phrase.Text != phraseConfirm!.Text)) { MessageBox.Show("As palavras-passe não coincidem."); return; }
            // Read every control on the UI thread BEFORE scheduling the worker.
            var request = new Dictionary<string, object?> { ["username"] = user?.Text, ["password"] = password?.Text, ["synthetic"] = demo.Checked, ["recovery_key"] = key.Text, ["recovery_password"] = phrase.Text };
            if (!updating) { request["http_port"] = (int)httpPort.Value; request["db_port"] = (int)dbPort.Value; }
            bool isRecovery = recovering.Checked;
            if (isRecovery) request["archive"] = archive!.Text;
            string action = isRecovery ? "recover" : updating ? "update" : "install";
            phaseTimer.Start();
            bool success = await WizardOperation.Execute(form, button, progress, status,
                () => { string file = PrivateRequest(request); return Task.Run(() => Run(release, action, file, package)); },
                error => error is UserError && !string.IsNullOrWhiteSpace(error.Message) ? error.Message : "A operação falhou. Preserve os dados e contacte a informática. Categoria: " + error.GetType().Name);
            phaseTimer.Stop();
            if (success) {
                MessageBox.Show(form, isRecovery ? "Backup restaurado e verificado. Serviços bloqueados até à conferência da informática. Não há publicação automática." : "Operação concluída. Dados e chaves conservados. Abra a aplicação pelo atalho.", "Gestão Vertente Aveludada");
                form.DialogResult = DialogResult.OK; form.Close();
            } else MessageBox.Show(form, status.Text, "Preparação interrompida — dados preservados", MessageBoxButtons.OK, MessageBoxIcon.Error);
        };
        return form.ShowDialog() == DialogResult.OK ? 0 : 1;
    }

    internal static string PrivateRequest(object value)
    {
        // Elevated process writes into its own private LocalAppData directory. Never argv.
        string directory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GVA-maintenance");
        Directory.CreateDirectory(directory);
        var acl = new System.Security.AccessControl.DirectorySecurity();
        acl.SetAccessRuleProtection(true, false);
        foreach (var sid in new[] { System.Security.Principal.WindowsIdentity.GetCurrent().User!, new System.Security.Principal.SecurityIdentifier("S-1-5-18"), new System.Security.Principal.SecurityIdentifier("S-1-5-32-544") })
            acl.AddAccessRule(new System.Security.AccessControl.FileSystemAccessRule(sid, System.Security.AccessControl.FileSystemRights.FullControl, System.Security.AccessControl.InheritanceFlags.ContainerInherit | System.Security.AccessControl.InheritanceFlags.ObjectInherit, System.Security.AccessControl.PropagationFlags.None, System.Security.AccessControl.AccessControlType.Allow));
        System.IO.FileSystemAclExtensions.SetAccessControl(new DirectoryInfo(directory), acl);
        string path = Path.Combine(directory, Guid.NewGuid() + ".json");
        File.WriteAllText(path, JsonSerializer.Serialize(value)); return path;
    }
}

sealed class UserError(string message) : Exception(message);

sealed class Dashboard : Form
{
    public Dashboard()
    {
        Text = "Gestão Vertente Aveludada"; Width = 560; Height = 340; StartPosition = FormStartPosition.CenterScreen;
        using var iconStream = new FileStream(Path.Combine(Program.Release, "app/static/branding/copo-com-vida.ico"), FileMode.Open);
        using var originalIcon = new Icon(iconStream);
        Icon = (Icon)originalIcon.Clone();
        var layout = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, Padding = new Padding(20) }; Controls.Add(layout);
        layout.Controls.Add(new Label { Text = "Gestão Vertente Aveludada — versão " + Program.State.GetProperty("version").GetString(), Width = 500, Height = 40 });
        string backup = Path.Combine(Program.Root, "runtime/backup/last-success.txt");
        layout.Controls.Add(new Label { Text = File.Exists(backup) ? "Backups automáticos ativos. A informática deve verificar cópias e restauros regularmente." : "Confirme com a informática a configuração e a última cópia de segurança.", Width = 500, Height = 55 });
        var open = new Button { Text = "Abrir a aplicação", Width = 250, Height = 45 };
        open.Click += (_, _) => { try {
            if (File.Exists(Path.Combine(Program.Root, "maintenance.json"))) throw new UserError("Instalação em manutenção. Contacte a informática; não apague dados.");
            using var pg = new ServiceController("GVAPostgres17"); using var web = new ServiceController("GVAWeb");
            if (pg.Status != ServiceControllerStatus.Running || web.Status != ServiceControllerStatus.Running) throw new UserError("Os serviços estão a iniciar ou indisponíveis. Aguarde e contacte a informática se persistir.");
            Process.Start(new ProcessStartInfo("http://127.0.0.1:" + Program.State.GetProperty("http_port").GetInt32() + "/") { UseShellExecute = true });
        } catch (Exception error) { MessageBox.Show(error is UserError ? error.Message : "Não foi possível abrir. Contacte a informática."); } };
        layout.Controls.Add(open);
        var backupButton = new Button { Text = "Backup manual (informática)", Width = 250, Height = 40 };
        backupButton.Click += (_, _) => Process.Start(new ProcessStartInfo(Environment.ProcessPath!, "--maintenance") { UseShellExecute = true }); layout.Controls.Add(backupButton);
    }
}

sealed class NativeService : ServiceBase
{
    readonly string kind;
    Process? child;
    volatile bool stopping;
    string stopFile = "";
    public NativeService(string kind)
    { this.kind = kind; ServiceName = kind switch { "postgres" => "GVAPostgres17", "web" => "GVAWeb", "backup" => "GVABackup", "publisher" => "GVAPublisher", _ => throw new ArgumentException("Serviço inválido") }; CanShutdown = true; }
    protected override void OnStart(string[] args)
    {
        RequestAdditionalTime(120000);
        stopFile = Path.Combine(Program.Root, "runtime", kind, "stop-" + Guid.NewGuid().ToString("N"));
        var info = new ProcessStartInfo(Path.Combine(Program.Release, "python/python.exe")) { WorkingDirectory = Path.Combine(Program.Release, "app"), UseShellExecute = false, CreateNoWindow = true, RedirectStandardError = true };
        foreach (var arg in new[] { "-s", "-B", "-m", "native_windows.cli", "service", "--kind", kind, "--stop-file", stopFile }) info.ArgumentList.Add(arg);
        info.Environment["GVA_NATIVE_CHANNEL"] = Program.Channel;
        info.Environment["PYTHONUTF8"] = "1"; info.Environment["PYTHONIOENCODING"] = "utf-8";
        info.StandardErrorEncoding = System.Text.Encoding.UTF8;
        child = Process.Start(info)!;
        string errorFile = Path.Combine(Program.Root, "runtime", kind, "last-error.txt");
        child.ErrorDataReceived += (_, e) => { if (e.Data != null) try { if (!File.Exists(errorFile) || new System.IO.FileInfo(errorFile).Length < 131072) File.AppendAllText(errorFile, e.Data + Environment.NewLine); } catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) { } };
        child.BeginErrorReadLine();
        child.EnableRaisingEvents = true;
        child.Exited += (_, _) => { if (!stopping) { ExitCode = 1067; Stop(); } };
        var deadline = DateTime.UtcNow.AddSeconds(kind == "postgres" ? 240 : 100);
        var extend = DateTime.UtcNow;
        while (!File.Exists(stopFile + ".ready"))
        {
            if (DateTime.UtcNow >= extend) { RequestAdditionalTime(30000); extend = DateTime.UtcNow.AddSeconds(20); }
            if (child.HasExited) throw new UserError("O serviço terminou durante o arranque. Consulte runtime/" + kind + "/last-error.txt; preserve os dados.");
            if (DateTime.UtcNow > deadline) {
                // Cooperative stop only. Never kill an initializing PostgreSQL.
                File.WriteAllText(stopFile, "stop"); ExitCode = 1067;
                throw new UserError("O arranque excedeu o limite; foi pedido encerramento seguro. Preserve os dados e o diário.");
            }
            Thread.Sleep(200);
        }
    }
    protected override void OnStop()
    {
        stopping = true;
        try { RequestAdditionalTime(100000); } catch (InvalidOperationException) { /* Windows shutdown; WAL remains durable. */ }
        File.WriteAllText(stopFile, "stop");
        // Never forcibly kill the database. PostgreSQL fast shutdown rolls back only
        // uncommitted work and flushes confirmed WAL before its process exits.
        if (child != null && !child.WaitForExit(90000)) { ExitCode = 1; throw new UserError("Encerramento excedeu o tempo; preserve os dados."); }
        File.Delete(stopFile);
        File.Delete(stopFile + ".ready");
    }
    protected override void OnShutdown() => OnStop();
}

static class Authenticode
{
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct FileInfo { public uint size; [MarshalAs(UnmanagedType.LPWStr)] public string path; public IntPtr file; public IntPtr subject; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct TrustData { public uint size; public IntPtr policy; public IntPtr sip; public uint ui; public uint revocation; public uint choice; public IntPtr file; public uint state; public IntPtr stateData; public IntPtr url; public uint flags; public uint context; public IntPtr signature; }
    [DllImport("wintrust.dll", ExactSpelling = true)] static extern int WinVerifyTrust(IntPtr hwnd, ref Guid action, ref TrustData data);
    internal static void Verify(string path, string expected)
    {
        var file = new FileInfo { size = (uint)Marshal.SizeOf<FileInfo>(), path = Path.GetFullPath(path) };
        IntPtr pointer = Marshal.AllocHGlobal(Marshal.SizeOf<FileInfo>());
        try {
            Marshal.StructureToPtr(file, pointer, false);
            var data = new TrustData { size = (uint)Marshal.SizeOf<TrustData>(), ui = 2, revocation = 1, choice = 1, file = pointer, flags = 0x80 };
            var action = new Guid("00AAC56B-CD44-11d0-8CC2-00C04FC295EE");
            if (WinVerifyTrust(new IntPtr(-1), ref action, ref data) != 0) throw new UserError("O instalador não tem uma assinatura Authenticode válida e confiável.");
            var cert = new X509Certificate2(X509Certificate.CreateFromSignedFile(path));
            if (!cert.GetCertHashString(HashAlgorithmName.SHA256).Equals(expected, StringComparison.OrdinalIgnoreCase)) throw new UserError("O certificado do instalador não pertence ao editor autorizado.");
        } finally { Marshal.DestroyStructure<FileInfo>(pointer); Marshal.FreeHGlobal(pointer); }
    }
}
