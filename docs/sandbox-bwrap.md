# Sandbox con bubblewrap (bwrap)

El MVP ejecuta las tools (`bash`, `read`, `write`, etc.) como subprocess directo del proceso de FastAPI. Eso significa que el agente comparte UID, red, `$HOME`, y filesystem con el servidor: un `rm -rf ~` mal colocado puede borrar cosas reales.

La responsabilidad de endurecer el entorno es del operador. Esta guía describe cómo envolver la ejecución con [bubblewrap](https://github.com/containers/bubblewrap), la herramienta unprivileged que usa Flatpak por debajo.

## Por qué bwrap y no Docker

- No requiere daemon ni root.
- Arranca en milisegundos (ideal para llamar por cada tool call si hiciera falta).
- Usa user namespaces de Linux directamente.
- Para Docker real, ver el backlog.

## Instalación

```bash
# Debian / Ubuntu
sudo apt install bubblewrap

# Fedora
sudo dnf install bubblewrap

# Arch
sudo pacman -S bubblewrap

# macOS: no disponible nativamente. Correr Mad dentro de una VM Linux
# (Lima, UTM, OrbStack) y aplicar bwrap ahí.
```

## Script de referencia: `scripts/run-sandboxed.sh`

Este script es el que el sandbox debería invocar en lugar de ejecutar el comando directamente. Recibe el directorio de la sesión y el comando a correr.

```bash
#!/usr/bin/env bash
# Uso: run-sandboxed.sh <workspace_dir> <comando> [args...]
set -euo pipefail

WORKSPACE="$1"
shift

exec bwrap \
  --unshare-all \
  --share-net \
  --die-with-parent \
  --new-session \
  --ro-bind /usr /usr \
  --ro-bind /lib /lib \
  --ro-bind /lib64 /lib64 \
  --ro-bind /bin /bin \
  --ro-bind /sbin /sbin \
  --ro-bind /etc/resolv.conf /etc/resolv.conf \
  --ro-bind /etc/ssl /etc/ssl \
  --ro-bind /etc/ca-certificates /etc/ca-certificates \
  --proc /proc \
  --dev /dev \
  --tmpfs /tmp \
  --bind "$WORKSPACE" /workspace \
  --chdir /workspace \
  --setenv HOME /workspace \
  --setenv PATH /usr/local/bin:/usr/bin:/bin \
  --unshare-user \
  --uid 1000 --gid 1000 \
  "$@"
```

## Qué garantiza esta configuración

- **`--unshare-all`** + **`--share-net`**: nuevo namespace de PID, mount, IPC, UTS y user; solo la red se comparte (para que `git clone` funcione). Si quieres cortar red, quita `--share-net`.
- **`--die-with-parent`**: si el proceso de Mad muere, el sandbox muere con él.
- **`--ro-bind`** del sistema base: el agente puede leer binarios y librerías pero no escribirlos.
- **`--bind $WORKSPACE /workspace`**: única ruta con escritura, montada en una ruta canónica dentro del sandbox.
- **`--tmpfs /tmp`**: `/tmp` efímero, desaparece al terminar.
- **`--unshare-user` + uid 1000**: el proceso ve uid 1000 aunque fuera seas otro user.
- `$HOME` dentro del sandbox es `/workspace`, así que herramientas que escriben configs (`git`, `pip --user`) no tocan tu home real.

## Integración con Mad

Dos opciones:

1. **Wrap del comando entero de la tool**: cuando el harness ejecuta `bash ...`, en lugar de `subprocess.run(["bash", "-c", cmd])` llama a `subprocess.run(["./scripts/run-sandboxed.sh", workspace_dir, "bash", "-c", cmd])`. Lo mismo para las demás tools.
2. **Wrap del proceso entero del harness** (cuando esté en worker separado, ver backlog): arrancas todo el worker dentro del sandbox y te ahorras invocar bwrap por cada tool.

Para el MVP, la opción 1 es suficiente.

## Limitaciones conocidas

- No protege contra abuso de red (el agente puede hacer requests a donde quiera si dejas `--share-net`).
- No limita CPU ni memoria. Para eso hay que combinar con `systemd-run --scope -p MemoryMax=2G -p CPUQuota=100%`.
- No corre en macOS nativo. Usa una VM Linux.
- Para aislamiento de red granular, considera `slirp4netns` o un namespace de red con reglas `nftables`.
