using System.Diagnostics;
using System.Text.Json;

namespace GVA;

internal static class SyntheticDemoWizard
{
    internal static string Parent => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "GVA-Homologacao");

    internal static int? Show(string channel, string root, string package, Func<string, string, string?, string?, int> run, Func<object, string> requestFile)
    {
        if (channel != "synthetic") return null;
        using var form = new Form { Text = "Demonstração sintética — só VM de homologação", Width = 650, Height = 440, StartPosition = FormStartPosition.CenterScreen };
        var flow = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false, Padding = new Padding(18) }; form.Controls.Add(flow);
        flow.Controls.Add(new Label { Text = "Cria uma demonstração com credenciais e recuperação exclusivas. Sem dados reais. O cofre local é cifrado para esta conta Windows; exporte o kit para recuperar noutra VM.", Width = 590, Height = 70 });
        var confirmed = new CheckBox { Text = "Confirmo que estou numa VM Windows 11 descartável e autorizada.", Width = 590, Height = 40 }; flow.Controls.Add(confirmed);
        var status = new Label { Text = "Pode optar pela configuração manual completa, incluindo recuperação.", Width = 590, Height = 55 }; flow.Controls.Add(status);
        var progress = new ProgressBar { Style = ProgressBarStyle.Marquee, Width = 570, Visible = false }; flow.Controls.Add(progress);
        var automatic = new Button { Text = "Criar demonstração automática", Width = 330, Height = 38 };
        var manual = new Button { Text = "Configuração manual / recuperar backup", Width = 330, Height = 38 };
        flow.Controls.Add(automatic); flow.Controls.Add(manual);
        var importKit = new Button { Text = "Abrir kit cifrado para recuperação noutra VM", Width = 380, Height = 38 };
        importKit.Click += (_, _) => OpenKit(channel); flow.Controls.Add(importKit);
        bool useManual = false;
        manual.Click += (_, _) => { useManual = true; form.Close(); };
        automatic.Click += async (_, _) => {
            bool approved = confirmed.Checked;
            automatic.Enabled = manual.Enabled = confirmed.Enabled = importKit.Enabled = false; form.ControlBox = false; progress.Visible = true;
            status.Text = "A verificar a VM e preparar a demonstração. Não encerre a operação.";
            DemoCredentials? credentials = null;
            try {
                await Task.Run(() => {
                    credentials = SyntheticDemo.Generate(channel, SyntheticDemo.Probe(), approved, root, Parent);
                    var request = new { username = credentials.Username, password = credentials.Password, synthetic = true, recovery_key = credentials.RecoveryKey, recovery_password = credentials.RecoveryPassword };
                    run(Path.Combine(package, "payload"), "install", requestFile(request), package);
                });
                ShowCredentials(form, channel, root, credentials!);
                form.DialogResult = DialogResult.OK; form.Close();
            } catch (Exception error) {
                status.Text = "Preparação interrompida. Preserve os dados e o diário. " + (error is UserError or InvalidOperationException ? error.Message : "Categoria: " + error.GetType().Name);
                MessageBox.Show(form, status.Text + (credentials is null ? "" : " Os dados de demonstração ficaram no cofre cifrado desta conta Windows."), "Demonstração não concluída", MessageBoxButtons.OK, MessageBoxIcon.Error);
            } finally { progress.Visible = false; automatic.Enabled = manual.Enabled = confirmed.Enabled = importKit.Enabled = true; form.ControlBox = true; }
        };
        var result = form.ShowDialog();
        return useManual ? null : result == DialogResult.OK ? 0 : 1;
    }

    internal static void ShowCredentials(IWin32Window owner, string channel, string root, DemoCredentials? data = null)
    {
        if (channel != "synthetic") throw new InvalidOperationException("Só demonstração sintética.");
        data ??= SyntheticDemo.Read(channel, Parent);
        using var form = new Form { Text = "Dados privados da demonstração", Width = 700, Height = 600, StartPosition = FormStartPosition.CenterParent };
        var flow = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.TopDown, WrapContents = false, AutoScroll = true, Padding = new Padding(16) }; form.Controls.Add(flow);
        flow.Controls.Add(new Label { Text = "Dados fictícios, exclusivos desta instalação. Não enviar para logs, chat ou GitHub. Guarde o kit e o código separadamente; o cofre DPAPI local não é portátil.", Width = 630, Height = 65 });
        var secretFields = new List<TextBox>();
        void Field(string label, string value, bool secret) {
            flow.Controls.Add(new Label { Text = label, Width = 630, Height = 25 });
            var box = new TextBox { Text = value, ReadOnly = true, UseSystemPasswordChar = secret, Width = 630 }; flow.Controls.Add(box);
            if (secret) secretFields.Add(box);
        }
        Field("Administrador fictício", data.Username, false); Field("Palavra-passe da demonstração", data.Password, true);
        Field("Frase da chave de recuperação", data.RecoveryPassword, true); Field("Ficheiro da chave privada cifrada", data.RecoveryKey, false); Field("Código de abertura do kit portátil (guardar separadamente)", data.KitCode, true);
        var reveal = new CheckBox { Text = "Mostrar os segredos nesta janela privada", Width = 630, Height = 35 };
        reveal.CheckedChanged += (_, _) => { foreach (var field in secretFields) field.UseSystemPasswordChar = !reveal.Checked; }; flow.Controls.Add(reveal);
        var export = new Button { Text = "Guardar kit cifrado para atualização/recuperação", Width = 530, Height = 40 };
        export.Click += (_, _) => {
            try {
                using var dialog = new SaveFileDialog { Filter = "Kit sintético cifrado|*.gvademo", FileName = "GVA-demonstracao.gvademo", OverwritePrompt = true };
                if (dialog.ShowDialog(form) != DialogResult.OK) return;
                byte[] encrypted = SyntheticDemo.EncryptKit(channel, data);
                using (var file = new FileStream(dialog.FileName, FileMode.CreateNew, FileAccess.Write)) { file.Write(encrypted); file.Flush(true); }
                SyntheticDemo.Protect(dialog.FileName, false);
                MessageBox.Show(form, "Kit cifrado guardado. Guarde o código mostrado separadamente. Sem esse código o kit não pode ser aberto.");
            } catch (Exception e) { MessageBox.Show(form, "Não foi possível guardar o kit. Não substitua ficheiros existentes. Categoria: " + e.GetType().Name); }
        }; flow.Controls.Add(export);
        var open = new Button { Text = "Abrir a demonstração no navegador", Width = 530, Height = 40 };
        open.Click += (_, _) => {
            try {
                using var state = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "installation.json")));
                if (state.RootElement.GetProperty("channel").GetString() != "synthetic" || state.RootElement.GetProperty("database").GetString() != "gva_native_synthetic" || File.Exists(Path.Combine(root, "maintenance.json"))) throw new InvalidOperationException();
                int port = state.RootElement.GetProperty("http_port").GetInt32();
                Process.Start(new ProcessStartInfo("http://127.0.0.1:" + port + "/entrar/") { UseShellExecute = true });
            } catch { MessageBox.Show(form, "A demonstração ainda não está disponível. Preserve os dados e consulte o diagnóstico."); }
        }; flow.Controls.Add(open);
        form.ShowDialog(owner);
    }

    internal static void OpenKit(string channel)
    {
        if (channel != "synthetic") throw new InvalidOperationException("Só demonstração sintética.");
        using var dialog = new OpenFileDialog { Filter = "Kit sintético cifrado|*.gvademo" };
        if (dialog.ShowDialog() != DialogResult.OK) return;
        using var prompt = new Form { Text = "Abrir kit sintético — código privado", Width = 620, Height = 170 };
        var code = new TextBox { Dock = DockStyle.Top, UseSystemPasswordChar = true };
        var next = new Button { Text = "Validar e extrair chave cifrada", Dock = DockStyle.Bottom, Height = 40 }; prompt.Controls.Add(code); prompt.Controls.Add(next);
        next.Click += (_, _) => {
            try {
                var fileInfo = new FileInfo(dialog.FileName); if (fileInfo.Length > 131072) throw new InvalidOperationException();
                var kit = SyntheticDemo.DecryptKit(channel, File.ReadAllBytes(dialog.FileName), code.Text);
                using var target = new SaveFileDialog { Filter = "Chave privada cifrada|*.pem", FileName = "GVA-recuperacao-demo.pem" };
                if (target.ShowDialog(prompt) != DialogResult.OK) return;
                byte[] encryptedKey = Convert.FromBase64String(kit.PrivateKey);
                using (var file = new FileStream(target.FileName, FileMode.CreateNew, FileAccess.Write)) { file.Write(encryptedKey); file.Flush(true); }
                SyntheticDemo.Protect(target.FileName, false);
                var data = new DemoCredentials(kit.Username, kit.Password, kit.RecoveryPassword, target.FileName, code.Text, "");
                ShowCredentials(prompt, channel, "", data); prompt.Close();
            } catch (Exception e) { MessageBox.Show(prompt, "Kit inválido, código incorreto ou destino existente. Nenhum dado foi importado. Categoria: " + e.GetType().Name); }
        };
        prompt.ShowDialog();
    }
}
