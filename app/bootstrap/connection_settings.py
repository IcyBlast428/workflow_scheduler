"""业务连接目录，与平台自身的启动连接配置分开管理。

目录密文保存在平台库；任务子进程使用启动时下发的授权快照，不直接读取目录。
保存通过数据库事务和版本比较防止覆盖其他管理员刚提交的修改。
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import re
from contextlib import contextmanager

PROFILE_ID = re.compile("[A-Za-z][A-Za-z0-9_-]{0,99}")


def _key(scope):
    secret = os.environ.get("WFS_CONNECTIONS_KEY") or os.environ.get("WFS_SECRET_KEY")
    if not secret and scope == "business" and os.environ.get("WFS_TASK_DATABASE_KEY"):
        return os.environ["WFS_TASK_DATABASE_KEY"].encode()
    if not secret:
        raise ValueError("请先配置 WFS_SECRET_KEY 或独立的 WFS_CONNECTIONS_KEY。")
    key = hashlib.sha256(
        b"wfs:database-connections:v1:" + scope.encode() + b"\x00" + secret.encode()
    ).digest()
    return base64.urlsafe_b64encode(key)


def _cipher(scope):
    from cryptography.fernet import Fernet

    return Fernet(_key(scope))


def task_database_key():
    return _key("business").decode()


@contextmanager
def _store():
    from app.bootstrap.auxiliary_store import gauss_store

    with gauss_store("connections") as db:
        yield db


def _decode(payload, identifier):
    from cryptography.fernet import InvalidToken

    try:
        return json.loads(_cipher("business").decrypt(payload))
    except InvalidToken:
        raise ValueError(
            "连接配置无法解密，请恢复原加密密钥；配置文件未被改写。"
        ) from None


def profiles():
    with _store() as db:
        rows = db.execute(
            "SELECT id,revision,payload FROM profiles WHERE id NOT LIKE '@%' ORDER BY id"
        ).fetchall()
    return {
        identifier: {**_decode(payload, identifier), "revision": revision}
        for identifier, revision, payload in rows
    }


def business_profile(identifier):
    """任务优先且只读自身授权快照；平台管理进程才从目录解析业务连接。"""
    scoped = os.environ.get("WFS_TASK_CONNECTIONS_JSON")
    if scoped is not None:
        # 空快照同样表示没有授权，不能因缺少某个连接而回退查询平台目录。
        profile = json.loads(scoped).get(identifier)
        if identifier == "platform" or not profile:
            raise PermissionError("此任务未获授权使用业务连接：" + str(identifier))
        if not profile.get("enabled", True):
            raise PermissionError("业务连接已停用：" + identifier)
        return profile
    if (
        identifier == "platform"
        or not isinstance(identifier, str)
        or (not PROFILE_ID.fullmatch(identifier))
    ):
        return None
    with _store() as db:
        row = db.execute(
            "SELECT payload FROM profiles WHERE id=?", (identifier,)
        ).fetchone()
    value = _decode(row[0], identifier) if row else None
    if value and (not value.get("enabled", True)):
        raise PermissionError("业务连接已停用：" + identifier)
    return value


def public_profile(profile):
    return {
        **{key: value for key, value in profile.items() if key != "password"},
        "password_set": bool(profile.get("password")),
    }


def validate(form):
    if not isinstance(form, dict):
        raise ValueError("连接信息必须为对象。")
    identifier = form.get("id")
    if not isinstance(identifier, str) or not PROFILE_ID.fullmatch(identifier):
        raise ValueError(
            "连接标识应以字母开头，最多 100 位，仅使用字母、数字、下划线或连字符。"
        )
    previous = profiles().get(identifier, {})
    from app.common.db.catalog import DATABASES, normalize

    dialect = normalize(form.get("dialect", previous.get("dialect", "mysql")))
    if identifier == "platform":
        raise ValueError("平台连接请到“平台数据库”页面管理；这里只保存任务业务连接。")
    if dialect not in DATABASES:
        raise ValueError("不支持的业务数据库类型：" + dialect)
    spec = DATABASES[dialect]
    result = {"id": identifier, "dialect": dialect, "charset": "utf8mb4"}
    for key, maximum in [("host", 253), ("database", 64), ("user", 100)]:
        value = form.get(key)
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value) > maximum
            or any((ord(c) < 33 for c in value))
        ):
            raise ValueError("请填写有效的数据库地址、库名和用户名。")
        result[key] = value.strip()
    pattern = "[A-Za-z0-9_$.-]+"
    if any((c in result["host"] for c in "/\\@?#")) or not re.fullmatch(
        pattern, result["database"]
    ):
        raise ValueError(
            "地址请只填主机名或 IP；数据库名称请使用字母、数字、下划线、美元符号或连字符。"
        )
    try:
        raw_port = form.get("port")
        port = (
            spec["port"]
            if raw_port in (None, "")
            else int(raw_port)
        )
        revision = int(form.get("revision", 0))
    except (ValueError, TypeError):
        raise ValueError("端口或配置版本无效。") from None
    if not 1 <= port <= 65535 or revision < 0:
        raise ValueError("端口应在 1 至 65535 之间。")
    password = form.get("password", "")
    if not isinstance(password, str) or len(password) > 1024:
        raise ValueError("密码格式或长度无效。")
    result.update(
        port=port, revision=revision, password=password or previous.get("password", "")
    )
    if not result["password"]:
        raise ValueError("新连接必须填写数据库密码。")
    mode = form.get("tls", previous.get("tls", "disabled"))
    if mode not in spec.get("tls_modes", ["verify_identity", "disabled"]):
        raise ValueError("TLS 配置无效。")
    ca = form.get("ssl_ca", "")
    if not isinstance(ca, str) or len(ca) > 1024 or "\x00" in ca:
        raise ValueError("CA 证书路径无效。")
    if mode == "verify_identity" and spec.get("ca_file", True) and (not ca or not Path(ca).is_file()):
        raise ValueError("启用 TLS 时请填写此服务器上有效的 CA 证书文件路径。")
    result.update(tls=mode, ssl_ca=ca if mode == "verify_identity" and spec.get("ca_file", True) else "")
    if spec.get("odbc_driver"):
        driver = form.get("driver") or (previous.get("driver") if previous.get("dialect") == dialect else None) or spec["default_driver"]
        if not isinstance(driver, str) or not 1 <= len(driver) <= 128 or any(ord(c) < 32 or c in ";{}\\/" for c in driver):
            raise ValueError("ODBC 驱动请填写已安装的驱动名称，不能填写路径或连接字符串。")
        result["driver"] = driver
    else:
        result["driver"] = ""
    for key, default, minimum, maximum in [
        ("pool_size", 1, 1, 20),
        ("max_overflow", 1, 0, 20),
        ("pool_recycle", 600, 30, 3600),
        ("pool_timeout", 10, 1, 120),
    ]:
        try:
            value = int(form.get(key, previous.get(key, default)))
        except (TypeError, ValueError):
            raise ValueError("连接池参数无效。") from None
        if not minimum <= value <= maximum:
            raise ValueError(f"{key} 应在 {minimum} 至 {maximum} 之间。")
        result[key] = value
    for key, maximum in [
        ("name", 100),
        ("purpose", 500),
        ("owner", 100),
        ("environment", 30),
    ]:
        value = form.get(key, previous.get(key, ""))
        if (
            not isinstance(value, str)
            or len(value) > maximum
            or any((ord(c) < 32 for c in value))
        ):
            raise ValueError("连接说明格式无效。")
        result[key] = value.strip()
    result["enabled"] = form.get("enabled", previous.get("enabled", True))
    if type(result["enabled"]) is not bool:
        raise ValueError("连接启用状态无效。")
    if identifier == "platform" and (not result["enabled"]):
        raise ValueError("不能在此停用平台库。")
    result["pool_enabled"] = form.get(
        "pool_enabled", previous.get("pool_enabled", True)
    )
    if not isinstance(result["pool_enabled"], bool):
        raise ValueError("连接池开关必须为布尔值。")
    return result


def save(profile):
    """Compare-and-swap the revision, without ever returning plaintext secrets."""
    with _store() as db:
        db.execute("BEGIN")
        row = db.execute(
            "SELECT revision FROM profiles WHERE id=?", (profile["id"],)
        ).fetchone()
        version = row[0] if row else 0
        if version != profile["revision"]:
            raise RuntimeError("连接信息已被修改，请刷新后重试。")
        payload = _cipher("business").encrypt(
            json.dumps(profile, ensure_ascii=False).encode()
        )
        db.replace(
            "profiles",
            ("id", "revision", "payload"),
            (profile["id"], version + 1, payload),
        )
    return {**public_profile(profile), "revision": version + 1}


def probe(profile, initialize=False):
    if initialize or profile["id"] == "platform":
        raise ValueError("平台表通过全新部署 SQL 初始化；页面仅测试业务连接。")
    return probe_business(profile)


def probe_business(profile):
    """使用独立临时标识探测候选连接，结果不替换已保存连接或污染其池。"""
    import uuid
    from app.common.db.factory import adapter_for
    from app.common.db.engine_pool import dispose

    identifier = "@probe-" + uuid.uuid4().hex
    adapter = None
    try:
        adapter = adapter_for({**profile, "id": identifier, "pool_enabled": False})
        sql = {
            "mysql": "SELECT VERSION()",
            "postgresql": "SELECT version()",
            "clickhouse": "SELECT version()",
            "gaussdb": "SELECT version()",
        }[profile["dialect"]]
        version = adapter.execute_query_sql(sql)[0][0]
        return {
            "connected": True,
            "ready": True,
            "version": str(version),
            "database": profile["database"],
            "missing": [],
        }
    except RuntimeError:
        raise ValueError(
            "当前服务缺少此数据库的驱动，请先按页面提示安装对应驱动。"
        ) from None
    except Exception:
        raise ValueError(
            "数据库连接测试失败。请核对地址、网络、驱动、账户权限和加密设置。"
        ) from None
    finally:
        if adapter is not None:
            adapter.close()
        dispose(identifier)
