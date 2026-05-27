import asyncio
import logging
import threading
import uuid
from queue import Queue

from canary_framework import service, on_config, on_start, on_end

from app.module.db_module.models import KbChunk
from app.module.db_module.service import DBService
from app.shared.llm.client import LLMClient

logger = logging.getLogger(__name__)


@service(name="EmbeddingService", deps=[DBService, LLMClient])
class EmbeddingService:
    @on_config
    def setup(self):
        self._queue: Queue = Queue()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = True

    @on_start
    async def start(self):
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("EmbeddingService thread started")

    @on_end
    async def end(self):
        self._running = False
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=30)
        logger.info("EmbeddingService shutdown")

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._worker_loop())

    async def _worker_loop(self):
        while self._running:
            try:
                item = self._queue.get(timeout=1)
            except Exception:
                continue
            if item is None:
                break
            await self._process_embed(item)

    def submit(self, item: dict):
        self._queue.put(item)

    async def embed_file(self, file_id: str, kb_id: str):
        async with self.db_service.transaction() as session:
            file_repo = self.db_service.file_repo(session)
            chunk_repo = self.db_service.chunk_repo(session)

            f = await file_repo.get_by_id(file_id)
            if not f or not f.parsed_text:
                logger.warning(f"No parsed text for file {file_id}")
                return
            if f.status != "parsed":
                logger.info(f"File {file_id} status is {f.status}, not 'parsed', skipping embed")
                return

            chunks = self._split_text(f.parsed_text)
            embeddings = await self.llm_client.embed([c["content"] for c in chunks])

            await chunk_repo.delete_by_file_id(file_id)

            for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                chk = KbChunk(
                    id=f"chk_{uuid.uuid4().hex[:20]}",
                    file_id=file_id,
                    kb_id=kb_id,
                    content=chunk["content"],
                    embedding=emb,
                    chunk_index=i,
                )
                await chunk_repo.create(chk)

            f.status = "success"
            await file_repo.update(f)

        logger.info(f"Embed completed: file_id={file_id}, chunks={len(chunks)}")

    async def _process_embed(self, item: dict):
        file_id = item.get("file_id")
        kb_id = item.get("kb_id")
        if file_id and kb_id:
            try:
                await self.embed_file(file_id, kb_id)
            except Exception as e:
                logger.error(f"Embed failed: file_id={file_id}, error={e}")
                try:
                    async with self.db_service.transaction() as session:
                        file_repo = self.db_service.file_repo(session)
                        f = await file_repo.get_by_id(file_id)
                        if f:
                            f.status = "failed"
                            f.error_msg = str(e)
                            await file_repo.update(f)
                except Exception as inner_e:
                    logger.error(f"Failed to update status for {file_id}: {inner_e}")

    async def search(self, query: str, kb_ids: list[str], file_ids: list[str] = None, top_k: int = 5) -> list[dict]:
        embedding_list = await self.llm_client.embed([query])
        query_embedding = embedding_list[0]

        async with self.db_service.transaction() as session:
            chunk_repo = self.db_service.chunk_repo(session)
            file_repo = self.db_service.file_repo(session)

            if file_ids:
                chunks = await chunk_repo.search_by_file(query_embedding, file_ids, top_k)
            else:
                chunks = await chunk_repo.search(query_embedding, kb_ids, top_k=top_k)

            results = []
            seen_file_ids = set()
            for chunk in chunks:
                if chunk.file_id not in seen_file_ids:
                    seen_file_ids.add(chunk.file_id)
                else:
                    file_cache = {}
                file_cache = {}
                f = file_cache.get(chunk.file_id) or await file_repo.get_by_id(chunk.file_id)
                if f:
                    file_cache[chunk.file_id] = f
                results.append({
                    "chunk_id": chunk.id,
                    "content": chunk.content,
                    "file_id": chunk.file_id,
                    "file_name": f.name if f else "",
                    "file_type": f.file_type if f else "",
                    "file_size": f.file_size if f else 0,
                    "oss_url": f.oss_url if f else "",
                    "chunk_index": chunk.chunk_index,
                })

            return results

    def _split_text(self, text: str) -> list[dict]:
        if not text:
            return []
        words = list(text)
        total = len(words)
        chunks = []
        start = 0
        index = 0
        while start < total:
            end = min(start + self.chunk_size, total)
            chunk_text = "".join(words[start:end])
            chunks.append({"content": chunk_text, "index": index})
            start = end - self.chunk_overlap
            index += 1
            if start <= 0:
                start = 1
            if start >= total:
                break
        return chunks
