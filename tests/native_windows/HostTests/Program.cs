using GVA;

internal static class Tests
{
    [STAThread]
    static int Main()
    {
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
