"""Small, bounded snapshots of the machine running the MCP service."""

import psutil


def get_cpu_usage() -> dict:
    return {"percent": psutil.cpu_percent(interval=0.1)}


def get_memory_usage() -> dict:
    memory = psutil.virtual_memory()
    return {"percent": memory.percent, "available_bytes": memory.available,
            "total_bytes": memory.total}


def get_disk_usage() -> dict:
    disk = psutil.disk_usage(".")
    return {"percent": disk.percent, "free_bytes": disk.free, "total_bytes": disk.total}


def get_process_list(limit: int = 10) -> list[dict]:
    """Top processes by memory, without command lines or environment variables."""
    if not 1 <= limit <= 20:
        raise ValueError("limit must be between 1 and 20")
    rows = []
    for process in psutil.process_iter(["pid", "name", "memory_percent"]):
        try:
            item = process.info
            rows.append({"pid": item["pid"], "name": item["name"] or "unknown",
                         "memory_percent": round(item["memory_percent"] or 0, 2)})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return sorted(rows, key=lambda row: row["memory_percent"], reverse=True)[:limit]
