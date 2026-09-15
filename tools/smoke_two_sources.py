import asyncio
import traceback
from datetime import datetime, timezone

from apps.vulntell.sources import UbuntuAdapter, UbuntuConfig, OSVAdapter, OSVConfig
from apps.vulntell.sources.ubuntu import UbuntuTransport
from apps.vulntell.sources.osv import OSVTransport
from apps.vulntell.sources.protocol import SourceRequest


async def check(name, adapter):
    try:
        request = SourceRequest(name, name, "v", datetime(2024, 9, 10, tzinfo=timezone.utc), datetime(2026, 9, 10, tzinfo=timezone.utc), page_size=100)
        page = await adapter.fetch_page(request, None)
        if hasattr(page, "records"):
            print(name, type(page).__name__, len(page.records), page.has_more, page.next_cursor)
            if page.records:
                print(page.records[0].payload)
        else:
            print(name, type(page).__name__, page)
    except Exception:
        traceback.print_exc()


asyncio.run(check("ubuntu", UbuntuAdapter(config=UbuntuConfig(timeout_seconds=30), transport=UbuntuTransport())))
asyncio.run(check("osv", OSVAdapter(config=OSVConfig(timeout_seconds=30), transport=OSVTransport())))
