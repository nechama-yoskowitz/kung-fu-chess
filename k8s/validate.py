"""
Offline structural validation for Kung-Fu Chess Kubernetes manifests.

Checks:
- All expected documents are present in each file
- Required fields: apiVersion, kind, metadata
- Correct kinds per file
- Namespace = kungfu-chess on every namespaced resource
- StatefulSet: serviceName set, replicas >= 1
- Game Server StatefulSet: KFC_SERVER_ID uses Downward API fieldRef
- Deployment: replicas >= 1
- Secret/ConfigMap: expected keys present

Run: pytest k8s/validate.py  OR  python k8s/validate.py
"""

import pathlib
import sys
import yaml

# (path, list of expected kind dicts per YAML document in the file)
EXPECTED = {
    "k8s/namespace.yaml": [
        {"kind": "Namespace", "apiVersion": "v1"},
    ],
    "k8s/secret.yaml": [
        {"kind": "Secret", "apiVersion": "v1"},
    ],
    "k8s/configmap.yaml": [
        {"kind": "ConfigMap", "apiVersion": "v1"},
    ],
    "k8s/postgres.yaml": [
        {"kind": "Service"},
        {"kind": "StatefulSet"},
    ],
    "k8s/redis.yaml": [
        {"kind": "Service"},
        {"kind": "Deployment"},
        {"kind": "PersistentVolumeClaim"},
    ],
    "k8s/game-server.yaml": [
        {"kind": "Service"},   # headless
        {"kind": "Service"},   # lb
        {"kind": "StatefulSet"},
    ],
    "k8s/gateway.yaml": [
        {"kind": "Service"},
        {"kind": "Deployment"},
    ],
}

SECRET_REQUIRED_KEYS = {"postgres-password", "postgres-dsn"}
CONFIGMAP_REQUIRED_KEYS = {
    "KFC_DB_BACKEND", "KFC_REDIS_ENABLED", "KFC_REDIS_URL",
    "KFC_WS_HOST", "KFC_WS_PORT", "KFC_HTTP_HOST", "KFC_HTTP_PORT",
    "KFC_LOG_LEVEL",
}
REQUIRED_FIELDS = ["apiVersion", "kind", "metadata"]


def validate_all():
    errors = []
    ok_count = 0

    for path, expected_docs in EXPECTED.items():
        p = pathlib.Path(path)
        if not p.exists():
            errors.append(f"MISSING FILE: {path}")
            continue

        try:
            docs = [d for d in yaml.safe_load_all(p.read_text(encoding="utf-8")) if d is not None]
        except yaml.YAMLError as exc:
            errors.append(f"{path}: YAML parse error: {exc}")
            continue

        if len(docs) != len(expected_docs):
            errors.append(
                f"{path}: expected {len(expected_docs)} document(s), got {len(docs)}"
            )
            continue

        for i, (doc, exp) in enumerate(zip(docs, expected_docs)):
            label = f"{path} doc[{i}] ({exp.get('kind', '?')})"

            # Required top-level fields
            for field in REQUIRED_FIELDS:
                if field not in doc:
                    errors.append(f"{label}: missing required field '{field}'")

            # Kind match
            got_kind = doc.get("kind")
            if got_kind != exp["kind"]:
                errors.append(f"{label}: kind={got_kind!r}, expected {exp['kind']!r}")

            # apiVersion (only checked when spec supplies it)
            if "apiVersion" in exp:
                got_av = doc.get("apiVersion")
                if got_av != exp["apiVersion"]:
                    errors.append(
                        f"{label}: apiVersion={got_av!r}, expected {exp['apiVersion']!r}"
                    )

            # Namespace must be 'kungfu-chess' for all namespaced resources
            if got_kind != "Namespace":
                ns = doc.get("metadata", {}).get("namespace")
                if ns != "kungfu-chess":
                    errors.append(
                        f"{label}: namespace={ns!r}, expected 'kungfu-chess'"
                    )

            # StatefulSet-specific checks
            if got_kind == "StatefulSet":
                spec = doc.get("spec", {})
                if not spec.get("serviceName"):
                    errors.append(f"{label}: StatefulSet missing spec.serviceName")
                replicas = spec.get("replicas", 0)
                if replicas < 1:
                    errors.append(f"{label}: StatefulSet replicas={replicas} (must be >= 1)")

                # Game server must give each pod a unique server ID via Downward API
                if "game-server" in path:
                    containers = (
                        spec.get("template", {})
                        .get("spec", {})
                        .get("containers", [])
                    )
                    for c in containers:
                        env_map = {e["name"]: e for e in c.get("env", [])}
                        sid_entry = env_map.get("KFC_SERVER_ID", {})
                        vf = sid_entry.get("valueFrom", {})
                        if "fieldRef" not in vf:
                            errors.append(
                                f"{label}: KFC_SERVER_ID is not sourced from "
                                "Downward API fieldRef"
                            )
                        else:
                            field_path = vf["fieldRef"].get("fieldPath", "")
                            if "metadata.name" not in field_path:
                                errors.append(
                                    f"{label}: KFC_SERVER_ID fieldRef.fieldPath="
                                    f"{field_path!r}, expected 'metadata.name'"
                                )

            # Deployment-specific checks
            if got_kind == "Deployment":
                replicas = doc.get("spec", {}).get("replicas", 0)
                if replicas < 1:
                    errors.append(f"{label}: Deployment replicas={replicas} (must be >= 1)")

            # Secret key checks
            if got_kind == "Secret":
                data = doc.get("data", {})
                missing = SECRET_REQUIRED_KEYS - set(data.keys())
                if missing:
                    errors.append(f"{label}: Secret missing keys: {sorted(missing)}")

            # ConfigMap key checks
            if got_kind == "ConfigMap":
                data = doc.get("data", {})
                missing = CONFIGMAP_REQUIRED_KEYS - set(data.keys())
                if missing:
                    errors.append(f"{label}: ConfigMap missing keys: {sorted(missing)}")

            ok_count += 1

    return errors, ok_count


def main():
    errors, ok_count = validate_all()
    if errors:
        print(f"VALIDATION FAILED ({len(errors)} error(s)):")
        for e in errors:
            print(f"  {e}")
        sys.exit(1)
    else:
        print(f"All {ok_count} manifest documents passed structural validation.\n")
        for path, docs in EXPECTED.items():
            kinds = ", ".join(d["kind"] for d in docs)
            print(f"  {path}: [{kinds}]")


if __name__ == "__main__":
    main()
