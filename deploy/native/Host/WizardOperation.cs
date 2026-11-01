using System.Text.Json;

namespace GVA;

// UI-only coordinator: all control changes and request snapshots stay on STA.
internal static class WizardOperation
{
    internal static async Task<bool> Execute(Form form, Button button, ProgressBar progress, Label status, Func<Task> action, Func<Exception, string> describe)
    {
        button.Enabled = false; form.ControlBox = false; progress.Visible = true;
        status.Text = "Operação em curso. Não encerre o assistente; os dados serão preservados em caso de falha.";
        try { await action(); status.Text = "Operação concluída."; return true; }
        catch (Exception error) { status.Text = describe(error); return false; }
        finally { progress.Visible = false; button.Enabled = true; form.ControlBox = true; }
    }

    internal static string Phase(string root)
    {
        try {
            using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "maintenance.json")));
            string? phase = document.RootElement.TryGetProperty("phase", out var p) ? p.GetString() : null;
            return phase switch {
                "postgres-binaries" => "A verificar as dependências privadas PostgreSQL…",
                "register-services" => "A registar os serviços…",
                "acl" => "A aplicar permissões privadas…",
                "cluster-bootstrap" => "A inicializar o PostgreSQL como conta virtual…",
                "django-migrations" => "A preparar o esquema da base nova…",
                "sql-grants" => "A restringir as permissões da aplicação…",
                "account-provisioning" => "A criar a conta inicial…",
                "android-identity" => "A preparar a identidade de assinatura…",
                "django-check" => "A validar a configuração…",
                _ => "Operação em curso. Aguarde; não encerre o assistente."
            };
        } catch (Exception error) when (error is IOException or UnauthorizedAccessException or JsonException or InvalidOperationException) {
            return "Operação em curso. Aguarde; não encerre o assistente.";
        }
    }
}
