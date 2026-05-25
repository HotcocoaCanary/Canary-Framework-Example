import asyncio
import logging
import threading
from queue import Queue

from app.module.db_module.models import KbChunk
from app.module.db_module.service import DBService
from app.shared.llm.client import LLMClient
from canary_framework import service, on_init, on_start, on_end, Context, config

logger = logging.getLogger(__name__)


@config
class ChunkWorkerConfig:
    chunk_size: int = 512
    chunk_overlap: int = 64


@service(name="ChunkWorker", deps=[DBService, LLMClient], config=ChunkWorkerConfig)
class ChunkWorker:
    @on_init
    def init(self, ctx: Context):
        self._queue: Queue = Queue()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._chunk_size = ctx.config.chunk_size
        self._chunk_overlap = ctx.config.chunk_overlap
        self._running = True

    @on_start
    async def start(self):
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("ChunkWorker thread started")

    @on_end
    async def end(self):
        self._running = False
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=30)
        logger.info("ChunkWorker shutdown")

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
            await self._process_chunk(item)

    def submit(self, item: dict):
        self._queue.put(item)

    async def _process_chunk(self, item: dict):
        kb_id = item.get("kb_id")
        file_ids = item.get("file_ids", [])
        task_id = item.get("task_id")

        for file_id in file_ids:
            try:
                async with self.db_service.transaction() as session:
                    file_record_repo = self.db_service.file_record_repo(session)
                    record = await file_record_repo.get_by_file_id(file_id)
                    if not record or not record.parsed_text:
                        logger.warning(f"No parsed text for file {file_id}")
                        continue

                    chunks = self._split_text(record.parsed_text)
                    embeddings = await self.llm_client.embed([c["content"] for c in chunks])

                    chunk_repo = self.db_service.chunk_repo(session)
                    await chunk_repo.delete_by_file_id(file_id)

                    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                        chk = KbChunk(
                            id=f"chk_{__import__('uuid').uuid4().hex[:20]}",
                            file_id=file_id,
                            kb_id=kb_id,
                            content=chunk["content"],
                            embedding=emb,
                            chunk_index=i,
                            page=chunk.get("page"),
                        )
                        await chunk_repo.create(chk)

                    record.status = "chunked"
                    await file_record_repo.update(record)

                logger.info(f"Chunk completed: file_id={file_id}, chunks={len(chunks)}")
            except Exception as e:
                logger.error(f"Chunk failed: file_id={file_id}, error={e}")

    def _split_text(self, text: str) -> list[dict]:
        if not text:
            return []
        words = list(text)
        total = len(words)
        chunks = []
        start = 0
        index = 0
        while start < total:
            end = min(start + self._chunk_size, total)
            chunk_text = "".join(words[start:end])
            chunks.append({"content": chunk_text, "page": None, "index": index})
            start = end - self._chunk_overlap
            index += 1
            if start <= 0:
                start = 1
            if start >= total:
                break
        return chunks
