import asyncio
import time
import threading
import sys
from typing import Coroutine, Any, Dict, List, Tuple


class Vync:
    def __init__(self, threaded: bool = True):
        self._threaded = threaded
        self._active_tasks: Dict[str, float] = {}
        self._finished_tasks: List[Tuple[str, float]] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        
        # asyncio.Event must be created in the loop it belongs to.
        # We'll initialize them later if threaded.
        self._all_done_event: Any = None 
        self._final_render_event = threading.Event()
        self._final_render_event.set()
        self._was_done = True

        if self._threaded:
            self._loop = asyncio.new_event_loop()
            self._all_done_event_threadsafe = threading.Event()
            self._all_done_event_threadsafe.set()
            
            self._loop_thread = threading.Thread(
                target=self._runSharedLoop, daemon=True
            )
            self._loop_thread.start()
            self._render_thread = threading.Thread(target=self._renderLoop, daemon=True)
            self._render_thread.start()
        else:
            self._loop = asyncio.get_event_loop()
            self._all_done_event = asyncio.Event()
            self._all_done_event.set()

    def stop(self):
        """Signals the background threads to stop and closes the loop."""
        self._stop_event.set()
        if self._threaded:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._loop_thread.join(timeout=1.0)
            self._render_thread.join(timeout=1.0)
            if self._loop.is_running():
                self._loop.stop()
            self._loop.close()

    def WaitAll(self, timeout: float = None):
        """Blocks until all tracked jobs are finished."""
        if self._threaded:
            if not self._all_done_event_threadsafe.wait(timeout=timeout):
                raise TimeoutError("WaitAll timed out")
            if not self._final_render_event.wait(timeout=timeout):
                raise TimeoutError("Final render timed out")
        else:
            # This shouldn't be called if not threaded and using await
            raise RuntimeError("WaitAll is blocking and should only be used in threaded mode. Use await_all() instead.")

    async def await_all(self):
        """Asynchronously waits for all tracked jobs to finish."""
        if self._threaded:
            # We need a way to wait for the thread-safe event asynchronously
            while not self._all_done_event_threadsafe.is_set():
                await asyncio.sleep(0.05)
        else:
            await self._all_done_event.wait()

    def TrackJob(
        self, name: str, coroutine: Coroutine[None, None, None], optional: bool = False
    ):
        with self._lock:
            if self._threaded:
                self._all_done_event_threadsafe.clear()
            else:
                self._all_done_event.clear()
            self._final_render_event.clear()
            self._was_done = False
            self._active_tasks[name] = time.time()

        async def _jobLogic():
            try:
                await coroutine
            except Exception as e:
                with self._lock:
                    start = self._active_tasks.get(name, time.time())
                    delta = time.time() - start
                    status = "[OPT FAIL]" if optional else "[ERR]"
                    color = "\033[93m" if optional else "\033[91m"
                    self._finished_tasks.append(
                        (
                            f"{color}{status}\033[0m {name} ({type(e).__name__}: {e})",
                            delta,
                        )
                    )
            finally:
                self._endTaskInternal(name)

        if self._threaded:
            asyncio.run_coroutine_threadsafe(_jobLogic(), self._loop)
        else:
            self._loop.create_task(_jobLogic())

    async def TrackAndAwait(self, name: str, coroutine: Coroutine):
        """Tracks a job and waits for it to finish, returning the result or raising the exception."""
        result_ref = [None]
        exception_ref = [None]

        async def _wrapper():
            try:
                result_ref[0] = await coroutine
            except Exception as e:
                exception_ref[0] = e
                raise

        self.TrackJob(name, _wrapper())
        await self.await_all()

        if exception_ref[0]:
            raise exception_ref[0]
        return result_ref[0]

    def _runSharedLoop(self):
        asyncio.set_event_loop(self._loop)
        self._all_done_event = asyncio.Event()
        self._all_done_event.set()
        self._loop.run_forever()

    def _endTaskInternal(self, name: str):
        with self._lock:
            if name in self._active_tasks:
                start_time = self._active_tasks.pop(name)
                delta = time.time() - start_time
                # Only add to finished if it hasn't been added by an error handler
                if not any(name in f[0] for f in self._finished_tasks):
                    self._finished_tasks.append(
                        (f"\033[92m[FINISHED]\033[0m {name}", delta)
                    )
            if not self._active_tasks:
                if self._threaded:
                    self._all_done_event_threadsafe.set()
                else:
                    self._all_done_event.set()

    def _renderLoop(self):
        last_line_count = 0
        is_atty = sys.stdout.isatty()
        
        while not self._stop_event.is_set():
            with self._lock:
                is_done = len(self._active_tasks) == 0
                if is_done and self._was_done:
                    pass
                elif is_atty:
                    now = time.time()
                    lines = []
                    for status_name, duration in self._finished_tasks:
                        lines.append(f"{status_name}: {duration:.2f}s")
                    for name, start_time in self._active_tasks.items():
                        lines.append(
                            f"\033[94m[ACTIVE]\033[0m {name}: {now - start_time:.2f}s"
                        )

                    if last_line_count > 0:
                        sys.stdout.write(f"\033[{last_line_count}A")

                    for line in lines:
                        sys.stdout.write(f"\r{line}\033[K\n")

                    if is_done:
                        last_line_count = 0
                        self._was_done = True
                        self._finished_tasks.clear()
                        self._final_render_event.set()
                    else:
                        last_line_count = len(lines)
                        self._was_done = False

                    sys.stdout.flush()
                elif is_done and not self._was_done:
                    # Non-interactive mode: just print finished tasks once
                    for status_name, duration in self._finished_tasks:
                        # Strip ANSI if not a TTY
                        clean_status = status_name.replace("\033[92m", "").replace("\033[91m", "").replace("\033[93m", "").replace("\033[0m", "")
                        print(f"{clean_status}: {duration:.2f}s")
                    self._was_done = True
                    self._finished_tasks.clear()
                    self._final_render_event.set()

            time.sleep(0.1)
