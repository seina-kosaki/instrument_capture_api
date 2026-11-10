import json
import re
import sys
from pathlib import PurePosixPath
from typing import Any

_SECRET_NAME = re.compile(r"^\.env(?:\..+)?$", re.IGNORECASE)
_SECRET_REFERENCE = re.compile(r"(?<![\w.-])\.env(?:\.[\w.-]+)?(?![\w.-])", re.IGNORECASE)
_PATH_KEYS = {
    "file", "files", "filepath", "filepaths", "file_path", "file_paths",
    "path", "paths", "target", "targets", "targetpath", "targetpaths",
    "target_path", "target_paths", "relative_path", "relative_paths",
    "filename", "filenames", "file_name", "file_names", "uri", "uris",
}
_COMMAND_KEYS = {"command", "cmd"}
_PATCH_KEYS = {"patch", "changes", "content"}
_PATCH_TARGET = re.compile(
    r"(?im)^\s*(?:\*\*\*\s*(?:delete|update|add)\s+file:|"
    r"\*\*\*\s*move\s+to:|(?:---|\+\+\+)\s+[ab]/)(.+?)\s*$"
)


def _decision(permission: str, reason: str) -> dict[str, str]:
    return {"permissionDecision": permission, "permissionDecisionReason": reason}


def _is_secret_path(value: str) -> bool:
    name = PurePosixPath(value.strip().replace("\\", "/")).name
    return bool(_SECRET_NAME.fullmatch(name) and name.lower() != ".env.example")


def _has_secret_reference(text: str) -> bool:
    return any(match.group(0).lower() != ".env.example" for match in _SECRET_REFERENCE.finditer(text))


def _is_destructive_git(command: str) -> bool:
    tokens = re.findall(r'"[^"]*"|\'[^\']*\'|[^\s;&|]+|[;&|]+', command.lower())
    options_with_values = {"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--config-env"}
    for index, token in enumerate(tokens):
        if token.strip("\"'") != "git":
            continue
        args = [item.strip("\"'").rstrip(",") for item in tokens[index + 1 :]]
        for separator in (";", "&&", "||", "|", "&"):
            if separator in args:
                args = args[: args.index(separator)]
                break
        cursor = 0
        while cursor < len(args) and args[cursor].startswith("-"):
            option = args[cursor]
            if option in options_with_values:
                cursor += 2
            elif option.startswith(("--git-dir=", "--work-tree=", "--namespace=", "--exec-path=", "--config-env=")):
                cursor += 1
            else:
                cursor += 1
        if cursor >= len(args):
            continue
        subcommand, subargs = args[cursor], args[cursor + 1 :]
        if subcommand == "clean":
            return True
        if subcommand == "reset" and any(arg == "--hard" or arg.startswith("--hard=") for arg in subargs):
            return True
        if subcommand == "push" and any(
            arg in {"-f", "--force", "--force-with-lease"}
            or arg.startswith(("--force=", "--force-with-lease="))
            or (arg.startswith("-") and not arg.startswith("--") and "f" in arg[1:])
            for arg in subargs
        ):
            return True
    return False


def _contains_protected_action(value: Any, key: str = "") -> bool:
    if isinstance(value, dict):
        return any(
            _contains_protected_action(child, child_key.lower())
            for child_key, child in value.items()
            if isinstance(child_key, str)
        )
    if isinstance(value, list):
        return any(_contains_protected_action(child, key) for child in value)
    if not isinstance(value, str):
        return False
    if key in _PATH_KEYS and _is_secret_path(value):
        return True
    if key in _COMMAND_KEYS:
        return _has_secret_reference(value) or _is_destructive_git(value)
    if key in _PATCH_KEYS:
        return any(_is_secret_path(match.group(1)) for match in _PATCH_TARGET.finditer(value))
    return False


def _is_shell_tool(tool_name: Any) -> bool:
    if not isinstance(tool_name, str):
        return False
    name = tool_name.strip().lower()
    return name in {
        "bash", "powershell", "pwsh", "sh", "zsh", "cmd", "terminal",
        "shell", "execute", "exec", "command",
    } or any(word in name for word in ("terminal", "shell", "execute", "command"))


def _raw_input_is_protected(tool_input: str, tool_name: Any) -> bool:
    if _is_secret_path(tool_input):
        return True
    if _contains_protected_action({"patch": tool_input}):
        return True
    return _is_shell_tool(tool_name) and (
        _has_secret_reference(tool_input) or _is_destructive_git(tool_input)
    )


def evaluate(event: Any) -> dict[str, str] | None:
    if not isinstance(event, dict):
        return None
    tool_name = event.get("toolName", event.get("tool_name", event.get("name", "")))
    tool_input = event.get(
        "toolArgs",
        event.get("tool_args", event.get("tool_input", event.get("toolInput", event.get("arguments")))),
    )
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (ValueError, RecursionError):
            if _raw_input_is_protected(tool_input, tool_name):
                return _decision(
                    "deny",
                    "秘密ファイルへのアクセス、読み取り、書き込み、漏えい、および破壊的なGit操作は禁止されています。",
                )
            return None
    if isinstance(tool_input, str) and _raw_input_is_protected(tool_input, tool_name):
        return _decision(
            "deny",
            "秘密ファイルへのアクセス、読み取り、書き込み、漏えい、および破壊的なGit操作は禁止されています。",
        )
    if _contains_protected_action(tool_input):
        return _decision(
            "deny",
            "秘密ファイルへのアクセス、読み取り、書き込み、漏えい、および破壊的なGit操作は禁止されています。",
        )
    return None


def main() -> int:
    try:
        event = json.load(getattr(sys.stdin, "buffer", sys.stdin))
    except (ValueError, UnicodeDecodeError, RecursionError):
        return 0
    result = evaluate(event)
    if result is not None:
        print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
