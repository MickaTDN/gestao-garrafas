using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Cryptography;
using System.Security.Principal;
using System.Text;
using System.Text.Json;

namespace GVA;

internal sealed record DemoCredentials(string Username, string Password, string RecoveryPassword, string RecoveryKey, string KitCode, string Directory);
internal sealed record DemoMachine(string Model, string Manufacturer, int ProductType, int Build);
internal sealed record DemoKit(string Username, string Password, string RecoveryPassword, string PrivateKey);

internal static class SyntheticDemo
{
    internal static void Guard(string channel, DemoMachine machine, bool confirmed, bool existing)
    {
        if (channel != "synthetic") throw new InvalidOperationException("Disponível apenas no canal sintético.");
        bool virtualBox = machine.Model == "VirtualBox" && (machine.Manufacturer == "innotek GmbH" || machine.Manufacturer == "Oracle Corporation");
        bool hyperV = machine.Model == "Virtual Machine" && machine.Manufacturer == "Microsoft Corporation";
        if (channel != "synthetic" || !confirmed || existing || machine.ProductType != 1 || machine.Build < 22000 || !(virtualBox || hyperV))
            throw new InvalidOperationException("A demonstração automática exige uma VM Windows 11 descartável confirmada, canal sintético e instalação nova. Use o modo manual para outros ensaios autorizados.");
    }

    internal static DemoMachine Probe()
    {
        var info = new ProcessStartInfo("powershell.exe") { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (string arg in new[] { "-NoProfile", "-NonInteractive", "-Command", "$c=Get-CimInstance Win32_ComputerSystem;$o=Get-CimInstance Win32_OperatingSystem;@{Model=$c.Model;Manufacturer=$c.Manufacturer;ProductType=[int]$o.ProductType;Build=[int]$o.BuildNumber}|ConvertTo-Json -Compress" }) info.ArgumentList.Add(arg);
        info.Environment.Remove("PSModulePath");
        using var process = Process.Start(info)!;
        var output = process.StandardOutput.ReadToEndAsync(); var error = process.StandardError.ReadToEndAsync();
        if (!process.WaitForExit(20000) || process.ExitCode != 0) throw new InvalidOperationException("Não foi possível confirmar a VM. Não foram gerados segredos.");
        return JsonSerializer.Deserialize<DemoMachine>(output.GetAwaiter().GetResult()) ?? throw new InvalidOperationException("Diagnóstico de VM inválido.");
    }

    internal static string Token() => Convert.ToBase64String(RandomNumberGenerator.GetBytes(32));

    internal static void RefuseReparse(string path)
    {
        // Check ancestors before creating files or applying elevated ACLs.
        // Never follow a pre-existing junction to another directory.
        for (var entry = new DirectoryInfo(Path.GetFullPath(path)); entry != null; entry = entry.Parent) {
            if (entry.LinkTarget != null || (entry.Exists && (entry.Attributes & FileAttributes.ReparsePoint) != 0))
                throw new InvalidOperationException("O cofre exige um caminho privado sem redirecionamentos.");
        }
    }

    internal static void Protect(string path, bool directory)
    {
        SecurityIdentifier[] identities = [WindowsIdentity.GetCurrent().User!, new("S-1-5-18"), new("S-1-5-32-544")];
        if (directory) {
            var acl = new DirectorySecurity(); acl.SetAccessRuleProtection(true, false);
            foreach (var sid in identities) acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl, InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
            FileSystemAclExtensions.SetAccessControl(new DirectoryInfo(path), acl);
        } else {
            var acl = new FileSecurity(); acl.SetAccessRuleProtection(true, false);
            foreach (var sid in identities) acl.AddAccessRule(new FileSystemAccessRule(sid, FileSystemRights.FullControl, AccessControlType.Allow));
            FileSystemAclExtensions.SetAccessControl(new FileInfo(path), acl);
        }
    }

    internal static DemoCredentials Generate(string channel, DemoMachine machine, bool confirmed, string root, string privateParent)
    {
        Guard(channel, machine, confirmed, System.IO.Directory.Exists(root));
        RefuseReparse(privateParent);
        System.IO.Directory.CreateDirectory(privateParent); Protect(privateParent, true);
        string directory = Path.Combine(privateParent, Guid.NewGuid().ToString("N"));
        System.IO.Directory.CreateDirectory(directory); Protect(directory, true);
        var data = new DemoCredentials("demo_" + Convert.ToHexString(RandomNumberGenerator.GetBytes(12)).ToLowerInvariant(), "Va!" + Token(), Token(), Path.Combine(directory, "recovery.pem"), Token(), directory);
        byte[] plain = JsonSerializer.SerializeToUtf8Bytes(data);
        try { File.WriteAllBytes(Path.Combine(directory, "demo.vault"), WindowsVault.Transform(plain, protect: true)); }
        finally { CryptographicOperations.ZeroMemory(plain); }
        File.WriteAllText(Path.Combine(privateParent, "active.txt"), directory); // Metadata only.
        return data;
    }

    internal static DemoCredentials Read(string channel, string privateParent)
    {
        if (channel != "synthetic") throw new InvalidOperationException("Disponível apenas no canal sintético.");
        RefuseReparse(privateParent);
        RefuseReparse(Path.Combine(privateParent, "active.txt"));
        string directory = File.ReadAllText(Path.Combine(privateParent, "active.txt"));
        string expectedParent = Path.GetFullPath(privateParent).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        if (!Path.GetFullPath(directory).StartsWith(expectedParent, StringComparison.OrdinalIgnoreCase) || Path.GetRelativePath(privateParent, directory).Contains(Path.DirectorySeparatorChar)) throw new InvalidOperationException("Cofre inválido.");
        if ((File.GetAttributes(directory) & FileAttributes.ReparsePoint) != 0) throw new InvalidOperationException("Cofre inválido.");
        RefuseReparse(Path.Combine(directory, "demo.vault"));
        byte[] plain = WindowsVault.Transform(File.ReadAllBytes(Path.Combine(directory, "demo.vault")), protect: false);
        try { return JsonSerializer.Deserialize<DemoCredentials>(plain) ?? throw new InvalidOperationException("Cofre inválido."); }
        finally { CryptographicOperations.ZeroMemory(plain); }
    }

    internal static byte[] EncryptKit(string channel, DemoCredentials data)
    {
        if (channel != "synthetic") throw new InvalidOperationException("Disponível apenas no canal sintético.");
        byte[] key = Convert.FromBase64String(data.KitCode), nonce = RandomNumberGenerator.GetBytes(12);
        string pem = File.ReadAllText(data.RecoveryKey);
        using (var rsa = RSA.Create()) rsa.ImportFromEncryptedPem(pem, data.RecoveryPassword);
        byte[] plain = JsonSerializer.SerializeToUtf8Bytes(new DemoKit(data.Username, data.Password, data.RecoveryPassword, Convert.ToBase64String(Encoding.UTF8.GetBytes(pem))));
        byte[] cipher = new byte[plain.Length], tag = new byte[16];
        try {
            using var aes = new AesGcm(key, 16); aes.Encrypt(nonce, plain, cipher, tag, "gva-synthetic-kit-v1"u8);
            return JsonSerializer.SerializeToUtf8Bytes(new { format = "gva-synthetic-kit", version = 1, nonce = Convert.ToBase64String(nonce), ciphertext = Convert.ToBase64String(cipher), tag = Convert.ToBase64String(tag) });
        } finally { CryptographicOperations.ZeroMemory(key); CryptographicOperations.ZeroMemory(plain); }
    }

    internal static DemoKit DecryptKit(string channel, byte[] archive, string code)
    {
        if (channel != "synthetic" || archive.Length > 131072) throw new InvalidOperationException("Kit inválido.");
        using var json = JsonDocument.Parse(archive); var r = json.RootElement;
        if (r.GetProperty("format").GetString() != "gva-synthetic-kit" || r.GetProperty("version").GetInt32() != 1) throw new InvalidOperationException("Formato de kit inválido.");
        byte[] key = Convert.FromBase64String(code), nonce = Convert.FromBase64String(r.GetProperty("nonce").GetString()!), cipher = Convert.FromBase64String(r.GetProperty("ciphertext").GetString()!), tag = Convert.FromBase64String(r.GetProperty("tag").GetString()!);
        byte[] plain = new byte[cipher.Length];
        try {
            using var aes = new AesGcm(key, 16); aes.Decrypt(nonce, cipher, tag, plain, "gva-synthetic-kit-v1"u8);
            var kit = JsonSerializer.Deserialize<DemoKit>(plain) ?? throw new InvalidOperationException("Kit inválido.");
            using (var rsa = RSA.Create()) rsa.ImportFromEncryptedPem(Encoding.UTF8.GetString(Convert.FromBase64String(kit.PrivateKey)), kit.RecoveryPassword);
            return kit;
        } finally { CryptographicOperations.ZeroMemory(key); CryptographicOperations.ZeroMemory(plain); }
    }
}

// DPAPI CurrentUser: no passwords, keys or secrets stored in cleartext files.
internal static class WindowsVault
{
    [StructLayout(LayoutKind.Sequential)] struct Blob { public int Length; public IntPtr Data; }
    [DllImport("crypt32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] static extern bool CryptProtectData(ref Blob data, string? description, IntPtr entropy, IntPtr reserved, IntPtr prompt, uint flags, out Blob output);
    [DllImport("crypt32.dll", SetLastError = true)] [return: MarshalAs(UnmanagedType.Bool)] static extern bool CryptUnprotectData(ref Blob data, IntPtr description, IntPtr entropy, IntPtr reserved, IntPtr prompt, uint flags, out Blob output);
    [DllImport("kernel32.dll")] static extern IntPtr LocalFree(IntPtr value);
    internal static byte[] Transform(byte[] input, bool protect)
    {
        var source = new Blob { Length = input.Length, Data = Marshal.AllocHGlobal(input.Length) };
        try {
            Marshal.Copy(input, 0, source.Data, input.Length);
            Blob output;
            bool ok = protect ? CryptProtectData(ref source, null, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 1, out output) : CryptUnprotectData(ref source, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, 1, out output);
            if (!ok) throw new CryptographicException("O cofre exige a conta Windows que o criou.");
            try { byte[] result = new byte[output.Length]; Marshal.Copy(output.Data, result, 0, result.Length); return result; }
            finally { for (int i = 0; i < output.Length; i++) Marshal.WriteByte(output.Data, i, 0); LocalFree(output.Data); }
        } finally { for (int i = 0; i < source.Length; i++) Marshal.WriteByte(source.Data, i, 0); Marshal.FreeHGlobal(source.Data); }
    }
}
