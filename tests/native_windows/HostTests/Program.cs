using GVA;

internal static class Tests
{
    [STAThread]
    static int Main()
    {
        string temp = Path.Combine(Path.GetTempPath(), "gva-retry-" + Guid.NewGuid().ToString("N"));
        try {
            string root = Path.Combine(temp, "data"), program = Path.Combine(temp, "program");
            Directory.CreateDirectory(root);
            string old = Path.Combine(program, "releases", "1.0.0"); Directory.CreateDirectory(Path.Combine(old, "payload"));
            File.WriteAllText(Path.Combine(old, "package.json"), "synthetic signed inventory fixture");
            string hash = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(Path.Combine(old, "package.json")))).ToLowerInvariant();
            File.WriteAllText(Path.Combine(root, "installation.json"), System.Text.Json.JsonSerializer.Serialize(new { version = "1.0.0", release = Path.Combine(old, "payload"), package_sha256 = hash }));
            string partial = Path.Combine(program, "releases", "1.1.0"); Directory.CreateDirectory(partial);
            File.WriteAllText(Path.Combine(partial, "untrusted.txt"), "do not reuse or remove");
            string chosen = RetryTarget.Select(root, program, "1.1.0");
            if (!chosen.StartsWith("1.1.0-attempt-") || chosen == RetryTarget.Select(root, program, "1.1.0") || File.ReadAllText(Path.Combine(partial, "untrusted.txt")) != "do not reuse or remove") throw new Exception();
            File.WriteAllText(Path.Combine(root, "maintenance.json"), "{}");
            bool refused = false; try { RetryTarget.Select(root, program, "1.1.0"); } catch { refused = true; } if (!refused) throw new Exception();
            File.Delete(Path.Combine(root, "maintenance.json")); File.WriteAllText(Path.Combine(old, "package.json"), "altered");
            refused = false; try { RetryTarget.Select(root, program, "1.1.0"); } catch { refused = true; } if (!refused) throw new Exception();
            Console.WriteLine("PASS: interrupted-copy retry selects fresh immutable attempt; preserves orphan; refuses journal and altered active manifest");
        } finally { if (Directory.Exists(temp)) Directory.Delete(temp, true); }
        Control.CheckForIllegalCrossThreadCalls = true;
        int result = 1;
        using var form = new Form();
        var button = new Button { Text = "Synthetic operation" };
        var progress = new ProgressBar { Visible = false };
        var status = new Label();
        form.Controls.Add(button); form.Controls.Add(progress); form.Controls.Add(status);
        void Check(bool ok) { if (!ok) throw new Exception("Wizard UI regression"); }
        form.Shown += async (_, _) => {
            try {
                bool success = await WizardOperation.Execute(form, button, progress, status,
                    () => { Check(!button.Enabled && !form.ControlBox && progress.Visible); return Task.Run(() => throw new InvalidOperationException("SYNTHETIC PRIVATE SENTINEL")); },
                    e => "Falha segura: " + e.GetType().Name);
                Check(!success && button.Enabled && form.ControlBox && !progress.Visible);
                Check(status.Text.Contains("InvalidOperationException") && !status.Text.Contains("SENTINEL"));
                success = await WizardOperation.Execute(form, button, progress, status,
                    () => { Check(!button.Enabled && progress.Visible); return Task.Delay(25); }, e => e.GetType().Name);
                Check(success && button.Enabled && form.ControlBox && !progress.Visible);
                Console.WriteLine("PASS: STA wizard progress, failure message, button restoration and success");
                result = 0;
            } catch (Exception e) { Console.WriteLine("FAIL: wizard " + e.GetType().Name); }
            finally { form.Close(); }
        };
        Application.Run(form);
        return result;
    }
}
