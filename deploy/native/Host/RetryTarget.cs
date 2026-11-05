using System.Text.Json;
using System.Security.Cryptography;

namespace GVA;

internal static class RetryTarget
{
    internal static string Select(string root, string program, string version)
    {
        string target = Path.Combine(program, "releases", version);
        foreach (var path in new[] { program, Path.Combine(program, "releases"), target })
            if ((Directory.Exists(path) || File.Exists(path)) && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidOperationException("Pasta de programa não segura; preserve os ficheiros.");
        if (!Directory.Exists(target) && !File.Exists(target)) return version;
        if (File.Exists(Path.Combine(root, "maintenance.json")))
            throw new InvalidOperationException("Manutenção pendente; não repetir a instalação.");
        using var document = JsonDocument.Parse(File.ReadAllText(Path.Combine(root, "installation.json")));
        var state = document.RootElement;
        string active = Path.GetFullPath(state.GetProperty("release").GetString()!);
        if (Version.Parse(state.GetProperty("version").GetString()!) >= Version.Parse(version)
            || state.TryGetProperty("uninstalled", out var removed) && removed.GetBoolean()
            || active.StartsWith(Path.GetFullPath(target) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException("A versão existente pode estar ativa. Nenhum ficheiro foi substituído.");
        string manifest = Path.Combine(Directory.GetParent(active)!.FullName, "package.json");
        string hash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(manifest))).ToLowerInvariant();
        if (hash != state.GetProperty("package_sha256").GetString())
            throw new InvalidOperationException("A instalação anterior não corresponde ao registo; preserve os dados.");
        // NEVER reuse, overwrite, rename or delete the orphan. Fresh immutable attempt.
        return version + "-attempt-" + Guid.NewGuid().ToString("N");
    }
}
