"""Short-lived test PKI, created only inside the caller's disposable private directory."""

import subprocess
from pathlib import Path


def certificates(root: Path, host: str):
    def openssl(*args):
        subprocess.run(["openssl", *map(str, args)], cwd=root, check=True, capture_output=True)

    root.mkdir(mode=0o700)
    (root / "index").touch()
    (root / "serial").write_text("1000\n")
    (root / "crlnumber").write_text("1000\n")
    (root / "ca.conf").write_text(
        """[ca]
default_ca=local
[local]
dir=.
database=$dir/index
new_certs_dir=$dir
certificate=$dir/ca.crt
private_key=$dir/ca.key
serial=$dir/serial
crlnumber=$dir/crlnumber
default_md=sha256
default_days=2
default_crl_days=2
policy=policy
unique_subject=no
[policy]
commonName=supplied
[client]
basicConstraints=critical,CA:false
keyUsage=critical,digitalSignature
extendedKeyUsage=clientAuth
[server]
basicConstraints=critical,CA:false
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth
subjectAltName=DNS:"""
        + host
        + "\n"
    )
    openssl(
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-days",
        "2",
        "-subj",
        "/CN=Synthetic WiFi Test CA",
        "-addext",
        "basicConstraints=critical,CA:true",
        "-keyout",
        "ca.key",
        "-out",
        "ca.crt",
    )
    for name, extension in (("server", "server"), ("device", "client"), ("revoked", "client")):
        openssl(
            "req",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-subj",
            "/CN=" + name,
            "-keyout",
            name + ".key",
            "-out",
            name + ".csr",
        )
        openssl(
            "ca",
            "-batch",
            "-config",
            "ca.conf",
            "-extensions",
            extension,
            "-in",
            name + ".csr",
            "-out",
            name + ".crt",
            "-notext",
        )
    openssl("ca", "-batch", "-config", "ca.conf", "-revoke", "revoked.crt")
    openssl("ca", "-config", "ca.conf", "-gencrl", "-out", "device-ca.crl")
    (root / "server-chain.crt").write_bytes((root / "server.crt").read_bytes())
    (root / "device-ca.crt").write_bytes((root / "ca.crt").read_bytes())
    # Linux read-only container bind. The enclosing test directory remains 0700.
    root.chmod(0o755)
    for name in ("server-chain.crt", "server.key", "device-ca.crt", "device-ca.crl"):
        (root / name).chmod(0o444)
