using System.Security.Cryptography;
using System.Text;
using GVA;

internal static class Tests
{
    static void Check(bool value, string label) { if (!value) throw new Exception(label); }
    static void Reject(Action action, string label) { try { action(); } catch { return; } throw new Exception(label); }
    static int Main()
    {
        string temporary = Path.Combine(Path.GetTempPath(), "gva-demo-test-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temporary);
        try {
            var vm = new DemoMachine("VirtualBox", "innotek GmbH", 1, 22631);
            foreach (var machine in new[] { vm with { Model = "Physical PC" }, vm with { ProductType = 3 }, vm with { Build = 19045 } }) Reject(() => SyntheticDemo.Guard("synthetic", machine, true, false), "unsafe machine");
            Reject(() => SyntheticDemo.Guard("release", vm, true, false), "release guard");
            Reject(() => SyntheticDemo.Guard("synthetic", vm, false, false), "approval guard");
            Reject(() => SyntheticDemo.Guard("synthetic", vm, true, true), "existing installation guard");
            string outside = Path.Combine(temporary, "untouched"), link = Path.Combine(temporary, "redirected");
            Directory.CreateDirectory(outside);
            var before = System.IO.FileSystemAclExtensions.GetAccessControl(new DirectoryInfo(outside)).GetSecurityDescriptorSddlForm(System.Security.AccessControl.AccessControlSections.All);
            Directory.CreateSymbolicLink(link, outside);
            try {
                Reject(() => SyntheticDemo.Generate("synthetic", vm, true, Path.Combine(temporary, "new-root"), link), "redirected vault parent");
                Reject(() => SyntheticDemo.Generate("synthetic", vm, true, Path.Combine(temporary, "new-root"), Path.Combine(link, "child")), "redirected vault ancestor");
                Check(!Directory.EnumerateFileSystemEntries(outside).Any(), "redirected target modified");
                Check(System.IO.FileSystemAclExtensions.GetAccessControl(new DirectoryInfo(outside)).GetSecurityDescriptorSddlForm(System.Security.AccessControl.AccessControlSections.All) == before, "redirected target ACL modified");
            } finally { Directory.Delete(link); }
            string parent = Path.Combine(temporary, "vaults");
            var first = SyntheticDemo.Generate("synthetic", vm, true, Path.Combine(temporary, "new-root"), parent);
            var second = SyntheticDemo.Generate("synthetic", vm, true, Path.Combine(temporary, "new-root-2"), parent);
            Check(first.Username != second.Username && first.Password != second.Password && first.RecoveryPassword != second.RecoveryPassword && first.KitCode != second.KitCode && first.RecoveryKey != second.RecoveryKey, "uniqueness");
            Check(SyntheticDemo.Read("synthetic", parent) == second, "DPAPI roundtrip");
            byte[] vault = File.ReadAllBytes(Path.Combine(first.Directory, "demo.vault"));
            Check(!Encoding.UTF8.GetString(vault).Contains(first.Password), "plaintext vault");
            var acl = System.IO.FileSystemAclExtensions.GetAccessControl(new DirectoryInfo(first.Directory));
            Check(acl.AreAccessRulesProtected, "private ACL");
            Reject(() => SyntheticDemo.Read("release", parent), "release vault access");
            using (var rsa = RSA.Create(3072)) File.WriteAllText(first.RecoveryKey, rsa.ExportEncryptedPkcs8PrivateKeyPem(first.RecoveryPassword, new PbeParameters(PbeEncryptionAlgorithm.Aes256Cbc, HashAlgorithmName.SHA256, 100000)));
            byte[] archive = SyntheticDemo.EncryptKit("synthetic", first);
            Check(!Encoding.UTF8.GetString(archive).Contains(first.Password) && !Encoding.UTF8.GetString(archive).Contains(first.KitCode), "plaintext portable kit");
            var kit = SyntheticDemo.DecryptKit("synthetic", archive, first.KitCode);
            Check(kit.Username == first.Username && kit.Password == first.Password && kit.RecoveryPassword == first.RecoveryPassword, "portable roundtrip");
            using (var rsa = RSA.Create()) rsa.ImportFromEncryptedPem(Encoding.UTF8.GetString(Convert.FromBase64String(kit.PrivateKey)), kit.RecoveryPassword);
            Reject(() => SyntheticDemo.DecryptKit("synthetic", archive, second.KitCode), "wrong kit code");
            archive[archive.Length / 2] ^= 1;
            Reject(() => SyntheticDemo.DecryptKit("synthetic", archive, first.KitCode), "tampered kit");
            Reject(() => SyntheticDemo.EncryptKit("release", first), "release kit export");
            Reject(() => SyntheticDemo.DecryptKit("release", [], first.KitCode), "release kit import");
            Console.WriteLine("PASS: synthetic VM/channel guards, unique secrets, private ACL, DPAPI, authenticated portable kit and production rejection");
            return 0;
        } catch (Exception error) { Console.WriteLine("FAIL: demo regression " + error.GetType().Name); return 1; }
        finally { Directory.Delete(temporary, true); } // Only this test's newly created directory.
    }
}
