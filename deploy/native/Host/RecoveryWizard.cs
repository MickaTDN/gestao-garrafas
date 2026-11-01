using System.Diagnostics;
using System.Text;
using System.Text.Json;

namespace GVA;

internal static class RecoveryWizard
{
    // Anonymous stdin pipe: credentials never become command arguments or request files.
    internal static JsonElement Run(string release, string action, object request, string? package = null)
    {
        string trust = Path.Combine(Path.GetTempPath(), "gva-public-trust-" + Guid.NewGuid() + ".json");
        File.WriteAllText(trust, Program.Trust.GetRawText());
        try {
            var info = new ProcessStartInfo(Path.Combine(release, "python", "python.exe")) {
                WorkingDirectory = Path.Combine(release, "app"), UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
            };
            foreach (string arg in new[] { "-s", "-B", "-m", "native_windows.cli", action, "--trust", trust, "--request-stdin" }) info.ArgumentList.Add(arg);
            if (package != null) { info.ArgumentList.Add("--package"); info.ArgumentList.Add(package); }
            info.Environment["GVA_NATIVE_CHANNEL"] = Program.Channel;
            info.Environment["PYTHONUTF8"] = "1"; info.Environment["PYTHONIOENCODING"] = "utf-8";
            using var process = Process.Start(info)!;
            var output = process.StandardOutput.ReadToEndAsync(); var errors = process.StandardError.ReadToEndAsync();
            process.StandardInput.Write(JsonSerializer.Serialize(request)); process.StandardInput.Close();
            process.WaitForExit();
            if (process.ExitCode != 0) throw new UserError(errors.GetAwaiter().GetResult().Trim());
            return JsonDocument.Parse(output.GetAwaiter().GetResult()).RootElement.Clone();
        } finally { File.Delete(trust); }
    }

    internal static bool Show(string release, bool recovering, string? package = null)
    {
        using var form = new Form { Text = recovering ? "Recuperar cópia de segurança" : "Criar cópia de segurança", Width = 660, Height = 670, StartPosition = FormStartPosition.CenterParent };
        var flow = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false, AutoScroll = true, Padding = new Padding(18) };
        form.Controls.Add(flow);
        void Label(string text, int height = 45) => flow.Controls.Add(new Label { Text = text, Width = 590, Height = height });
        TextBox Field(string label, bool secret = false) { Label(label); var field = new TextBox { Width = 580, UseSystemPasswordChar = secret }; flow.Controls.Add(field); return field; }
        Label(recovering ? "Selecione a cópia e a credencial. A recuperação usa um cluster novo e preserva os dados anteriores. Confirme que a instalação de origem está parada." : "Guarde a cópia fora da instalação. O ficheiro é cifrado, autenticado e testado por restauro antes da exportação.", 60);
        var archive = Field(recovering ? "Cópia .gvabackup" : "Guardar cópia .gvabackup (ficheiro novo)");
        var browse = new Button { Text = "Escolher ficheiro…", Width = 220 };
        browse.Click += (_, _) => {
            if (recovering) { using var d = new OpenFileDialog { Filter = "Cópia cifrada|*.gvabackup" }; if (d.ShowDialog(form) == DialogResult.OK) archive.Text = d.FileName; }
            else { using var d = new SaveFileDialog { Filter = "Cópia cifrada|*.gvabackup", FileName = "GVA-" + DateTime.Now.ToString("yyyyMMdd-HHmmss") + ".gvabackup", OverwritePrompt = true }; if (d.ShowDialog(form) == DialogResult.OK) archive.Text = d.FileName; }
        }; flow.Controls.Add(browse);
        var credential = Field(recovering ? "Credencial da cópia portátil (ou código do kit antigo)" : "Frase de recuperação portátil (mínimo 16 caracteres). Guarde-a separadamente da cópia.", true);
        TextBox? confirm = recovering ? null : Field("Confirmar frase de recuperação portátil", true);
        var kit = Field("Apenas para backups antigos / primeira exportação: kit .gvademo ou chave original (opcional)");
        var chooseKit = new Button { Text = "Escolher kit antigo…", Width = 220 };
        chooseKit.Click += (_, _) => { using var d = new OpenFileDialog { Filter = "Kit de demonstração|*.gvademo|Chave original de recuperação|*.pem" }; if (d.ShowDialog(form) == DialogResult.OK) kit.Text = d.FileName; }; flow.Controls.Add(chooseKit);
        var oldCode = recovering ? null : Field("Código do kit / frase da chave original (apenas primeira exportação)", true);
        Label("A cópia Windows contém os dados do servidor. Preferências e encomendas guardadas só no Android exigem a exportação local da PWA. O Wi-Fi será reativado após aprovação no destino.", 65);
        var button = new Button { Text = recovering ? "Validar e rever recuperação" : "Criar cópia de segurança", Width = 300, Height = 42 }; flow.Controls.Add(button);
        var progress = new ProgressBar { Width = 580, Style = ProgressBarStyle.Marquee, Visible = false }; flow.Controls.Add(progress);
        var status = new Label { Width = 590, Height = 100 }; flow.Controls.Add(status);
        button.Click += async (_, _) => {
            if (!recovering && credential.Text != confirm!.Text) { MessageBox.Show(form, "As frases não coincidem."); return; }
            var request = new Dictionary<string, object?> { [recovering ? "archive" : "destination"] = archive.Text, [recovering ? "credential" : "portable_password"] = credential.Text };
            if (!string.IsNullOrWhiteSpace(kit.Text)) {
                request[Path.GetExtension(kit.Text).Equals(".gvademo", StringComparison.OrdinalIgnoreCase) ? "demo_kit" : "recovery_key"] = kit.Text;
                request["credential"] = recovering ? credential.Text : oldCode!.Text;
                request["recovery_password"] = recovering ? credential.Text : oldCode!.Text;
            } else if (!recovering && Program.Channel == "synthetic" && !File.Exists(Path.Combine(Program.Root, "secrets", "recovery-envelope.json"))) {
                try {
                    var data = SyntheticDemo.Read(Program.Channel, SyntheticDemoWizard.Parent);
                    request["recovery_private_b64"] = Convert.ToBase64String(File.ReadAllBytes(data.RecoveryKey));
                    request["recovery_password"] = data.RecoveryPassword;
                } catch { MessageBox.Show(form, "Selecione o kit antigo e o respetivo código. O cofre desta conta Windows não está disponível."); return; }
            }
            bool complete = false;
            bool success = await WizardOperation.Execute(form, button, progress, status, async () => {
                if (!recovering) {
                    var result = await Task.Run(() => Run(release, "portable-backup", request));
                    MessageBox.Show(form, "Cópia cifrada exportada e restauro verificado.\nSHA-256: " + result.GetProperty("sha256").GetString() + "\nGuarde a credencial separadamente.");
                    complete = true;
                } else {
                    var preview = await Task.Run(() => Run(release, "recovery-preview", request, package));
                    string summary = "Origem: " + preview.GetProperty("instance").GetString() + "\nVersão: " + preview.GetProperty("version").GetString() + "\n";
                    var labels = new Dictionary<string, string> { ["inventory_reference"] = "Referências", ["inventory_movement"] = "Movimentos e inventários", ["inventory_movementline"] = "Linhas de movimentos", ["inventory_location"] = "Localizações", ["inventory_sector"] = "Setores", ["accounts_user"] = "Utilizadores", ["accounts_accessprofile"] = "Perfis", ["inventory_document"] = "Documentos e assinaturas", ["inventory_auditevent"] = "Registos de auditoria" };
                    foreach (var table in preview.GetProperty("rows").EnumerateObject()) if (labels.TryGetValue(table.Name, out var label)) summary += label + ": " + table.Value.GetInt32() + "\n";
                    summary += "\nTodos os restantes dados persistentes do servidor também serão verificados.\nAlterações posteriores ao backup não estão nesta cópia.\nA instalação anterior será preservada.";
                    using var review = new Form { Text = "Conferir recuperação", Width = 650, Height = 550, StartPosition = FormStartPosition.CenterParent };
                    var rows = new TextBox { Dock = DockStyle.Fill, Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, Text = summary.Replace("\n", Environment.NewLine) };
                    var accept = new Button { Dock = DockStyle.Bottom, Height = 55, Text = "Confirmo: origem parada e substituir dados pelo backup" };
                    review.Controls.Add(rows); review.Controls.Add(accept); accept.Click += (_, _) => review.DialogResult = DialogResult.OK;
                    if (review.ShowDialog(form) != DialogResult.OK) return;
                    request["confirmed"] = true; request["source_offline"] = true; request["token"] = preview.GetProperty("token").GetString();
                    await Task.Run(() => Run(release, "recovery-restore", request, package));
                    MessageBox.Show(form, "Recuperação verificada. Aplicação e backups disponíveis neste computador. Dados anteriores preservados. Acesso Wi-Fi aguarda aprovação de rede.");
                    complete = true;
                }
            }, error => error is UserError ? error.Message : "Operação interrompida; dados conservados. Categoria: " + error.GetType().Name);
            if (success && complete) { form.DialogResult = DialogResult.OK; form.Close(); }
            else if (!success) MessageBox.Show(form, status.Text, "Operação não concluída", MessageBoxButtons.OK, MessageBoxIcon.Error);
        };
        return form.ShowDialog() == DialogResult.OK;
    }
}
