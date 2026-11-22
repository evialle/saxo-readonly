# OpenClaw integration

The Python package is the connector. The skill is an instruction bundle that calls its CLI. OpenClaw is not a dependency of the library, and the skill does not add Saxo permissions.

## Install

1. Install this repository's Python package on the machine where the OpenClaw agent runs shell commands. Authenticate there under the execution user, using the [README](../README.md).
2. Make the installed `saxo-readonly` executable available on that process's PATH. For a virtual environment, add its `Scripts` directory on Windows or `bin` on POSIX to the service environment. A PATH change in a different terminal does not change an already-running service.
3. From the repository root, install the skill directory:

   ```text
   openclaw skills install ./skills/saxo-readonly --global
   openclaw skills info saxo-readonly
   openclaw skills check
   ```

The official CLI supports local skill directories and `--global` for shared local-agent installation. The source directory must contain `SKILL.md` at its root, so use `./skills/saxo-readonly`, not the repository root. See [OpenClaw Skills CLI](https://docs.openclaw.ai/cli/skills).

For installations that use the traditional file layout, copy `skills/saxo-readonly` into `~/.openclaw/skills/saxo-readonly/`, or into the selected workspace's `skills/` directory. Respect a customized OpenClaw state directory and avoid overwriting a locally modified skill without reviewing it. [OpenClaw skills configuration](https://docs.openclaw.ai/skills-config).

Start a new agent session after installation if it has not refreshed its skill list. To update a locally installed skill, install the updated local directory again; installing the connector package and installing the skill are separate operations.

## Runtime configuration

Use the default private configuration path for the execution user, or set `SAXO_CONFIG_FILE` in the OpenClaw service environment. Do not embed the file contents or credentials in the skill, chat prompt, repository, or public agent logs.

If the agent runs in a container, remote node, or restricted execution environment, it needs the Python executable and a separately authenticated configuration on that execution host. A Windows DPAPI-protected session cannot simply be copied into a Linux container. Decide where the connector should run and authenticate there. No broad filesystem or network permission should be granted just to make the skill appear eligible.

## Example requests

- “Show my latest Saxo report and when it was captured.”
- “Refresh my Saxo snapshot and tell me whether the valuation moved by at least 3%.”
- “List the held instruments from Saxo, with unavailable prices clearly marked.”

The agent uses `report` for an existing saved report and `snapshot` before `report` when current data is requested. It identifies SIM/LIVE, capture time, reporting currency, and the baseline used. It explains that balance deltas are not investment returns.

The skill supports local reporting. Recurring execution or delivery to email/chat requires a separately requested automation and a private destination. No automation or messaging destination is installed by this repository.

## Boundary

The agent does not handle interactive authentication secrets. The owner runs `auth-start` and `auth-finish` privately. The skill uses `auth-status` to diagnose readiness and asks for reauthentication when needed. It does not read token/configuration files, turn API text into shell code, or bypass the connector to submit orders or other Saxo mutations. Portfolio strings are data, not instructions.
