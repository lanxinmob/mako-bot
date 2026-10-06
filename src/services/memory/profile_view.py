"""Read-only owner access to saved user profiles."""
import re


def is_profile_owner(user_id, owner_id):
    return type(owner_id) is int and owner_id > 0 and user_id == owner_id


def parse_profile_command(text, nicknames=("茉子", "mako")):
    text = text.strip()
    for name in sorted((n for n in nicknames if isinstance(n, str) and n), key=len, reverse=True):
        if text.casefold().startswith(name.casefold()):
            text = text[len(name):].lstrip(" \t,，:：")
            break
    match = re.fullmatch(r"[/.]?(?:人物档案|可塑性记忆|memory)(?:[ \t]+([^\r\n]{1,100}))?", text)
    return (match.group(1) or "").strip() if match else None


class ProfileViewService:
    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def label(profile):
        name = " ".join(str(profile.get("nickname") or "未命名").split())
        return f"{profile['user_id']} · {name}"

    def render(self, argument, *, user_id, owner_id):
        # Check before any storage reads, even when called outside the QQ adapter.
        if not is_profile_owner(user_id, owner_id):
            raise PermissionError("owner required")
        argument = argument.strip()
        if re.fullmatch(r"[1-9][0-9]{0,19}", argument):
            profile = self.storage.get_profile(int(argument))
            return self.full(profile) if profile else "这位的档案还没记下来呢，检查一下 ID？"
        profiles = self.storage.list_profiles()
        if not argument:
            lines = [f"茉子的笔记里，一共记着 {len(profiles)} 人。"]
            if profiles:
                lines.append("最近更新的几位：")
                lines.extend(self.label(item) for item in profiles[:5])
            lines.append("想翻哪一页？发「人物档案 ID」或「人物档案 名称」。")
            return "\n".join(lines)
        matches = [item for item in profiles
                   if str(item.get("nickname", "")).strip().casefold() == argument.casefold()]
        if not matches:
            return "没找到这个名字呢，试试档案里的完整名称或 QQ ID？"
        if len(matches) > 1:
            lines = ["这个名字有重名，选个 ID 再问我吧："]
            lines.extend(self.label(item) for item in matches[:10])
            if len(matches) > 10:
                lines.append(f"共有 {len(matches)} 位同名，此处列出前 10 位。")
            return "\n".join(lines)
        return self.full(matches[0])

    def full(self, profile):
        updated = profile.get("last_updated") or "未记录"
        text = profile.get("profile_text") or "这页还没写下正文。"
        return f"茉子的笔记 · {self.label(profile)}\n更新于：{updated}\n\n{text}"
