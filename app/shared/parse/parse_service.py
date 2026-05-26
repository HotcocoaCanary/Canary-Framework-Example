import logging
import os
import tempfile

logger = logging.getLogger(__name__)


class ParseService:
    async def parse(self, *, text: str = None, url: str = None, file: bytes = None,
                    file_name: str = None) -> tuple[str, dict]:
        if text is not None:
            return text, {}
        if url is not None:
            return await self._parse_url(url)
        if file is not None:
            return await self._parse_file(file, file_name)
        raise ValueError("At least one of text, url, or file must be provided")

    async def _parse_url(self, url: str) -> tuple[str, dict]:
        import aiohttp

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    html = await resp.text()
            from markitdown import MarkItDown
            md = MarkItDown()
            result = md.convert(html)
            title = ""
            if "<title>" in html:
                start = html.index("<title>") + 7
                end = html.index("</title>", start)
                title = html[start:end].strip()
            return result.text_content or "", {"title": title}
        except Exception as e:
            logger.error(f"URL parse failed: {url}, error={e}")
            raise

    async def _parse_file(self, data: bytes, file_name: str) -> tuple[str, dict]:
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else "txt"
        suffix = f".{ext}"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            if ext in ("txt", "md", "markdown"):
                with open(tmp_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
            else:
                from markitdown import MarkItDown
                md = MarkItDown()
                result = md.convert(tmp_path)
                text = result.text_content or ""
            metadata = {
                "file_name": file_name,
                "file_type": ext,
                "file_size": len(data),
            }
            return text, metadata
        finally:
            os.unlink(tmp_path)
