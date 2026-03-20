import asyncio
import time
import threading
import base64
import sys
from typing import Coroutine


class Vync:
  def __init__(self, threaded: bool = True):
    self._threaded = threaded
    self._active_tasks: dict[str, float] = {}
    self._finished_tasks: list[tuple[str, float]] = []
    self._lock = threading.Lock()
    self._stop_event = threading.Event()
    self._all_done_event = threading.Event()
    self._all_done_event.set()
    self._final_render_event = threading.Event()
    self._final_render_event.set()
    self._was_done = True

    if self._threaded:
      self._loop = asyncio.new_event_loop()
      self._loop_thread = threading.Thread(target=self._runSharedLoop, daemon=True)
      self._loop_thread.start()
      self._render_thread = threading.Thread(target=self._renderLoop, daemon=True)
      self._render_thread.start()
    else:
      self._loop = asyncio.get_event_loop()

  def WaitAll(self):
    if self._threaded:
      self._all_done_event.wait()
      self._final_render_event.wait()

  def TrackJob(self, name: str, coroutine: Coroutine[None, None, None], optional: bool = False):
    cr_key = base64.b64encode(name.encode()).decode()

    with self._lock:
      self._all_done_event.clear()
      self._final_render_event.clear()
      self._was_done = False
      self._active_tasks[cr_key] = time.time()

    async def _jobLogic():
      try:
        await coroutine
      except Exception as e:
        with self._lock:
          dec = base64.b64decode(cr_key.encode()).decode()
          start = self._active_tasks.get(cr_key, time.time())
          delta = time.time() - start
          if optional:
            self._finished_tasks.append(
              (f'\033[93m[OPT FAIL]\033[0m {dec} ({type(e).__name__} {e})', delta)
            )
          else:
            self._finished_tasks.append(
              (f'\033[91m[ERR]\033[0m {dec} ({type(e).__name__} {e})', delta)
            )
      finally:
        self._endTaskInternal(cr_key)

    if self._threaded:
      asyncio.run_coroutine_threadsafe(_jobLogic(), self._loop)
    else:
      self._loop.run_until_complete(_jobLogic())

  def TrackAndAwait(self, name: str, coroutine: Coroutine):
    result_ref = [None]
    exception_ref = [None]

    async def _wrapper():
      try:
        result_ref[0] = await coroutine
      except Exception as e:
        exception_ref[0] = e
        raise

    self.TrackJob(name, _wrapper())
    self.WaitAll()

    if exception_ref[0]:
      raise exception_ref[0]
    return result_ref[0]

  def _runSharedLoop(self):
    asyncio.set_event_loop(self._loop)
    self._loop.run_forever()

  def _endTaskInternal(self, cr_key: str):
    with self._lock:
      if cr_key in self._active_tasks:
        start_time = self._active_tasks.pop(cr_key)
        name = base64.b64decode(cr_key.encode()).decode()
        delta = time.time() - start_time
        if not any(name in f[0] for f in self._finished_tasks):
          self._finished_tasks.append((f'\033[92m[FINISHED]\033[0m {name}', delta))
      if not self._active_tasks:
        self._all_done_event.set()

  def _renderLoop(self):
    last_line_count = 0
    while True:
      with self._lock:
        is_done = len(self._active_tasks) == 0
        if is_done and self._was_done:
          pass
        else:
          now = time.time()
          lines = []
          for status_name, duration in self._finished_tasks:
            lines.append(f'{status_name}: {duration:.2f}s')
          for key, start_time in self._active_tasks.items():
            name = base64.b64decode(key.encode()).decode()
            lines.append(f'\033[94m[ACTIVE]\033[0m {name}: {now - start_time:.2f}s')
          
          if last_line_count > 0:
            sys.stdout.write(f'\033[{last_line_count}A')
          
          for line in lines:
            sys.stdout.write(f'\r{line}\033[K\n')
            
          if is_done:
            last_line_count = 0
            self._was_done = True
            self._finished_tasks.clear()
            self._final_render_event.set()
          else:
            last_line_count = len(lines)
            self._was_done = False
            
          sys.stdout.flush()
      time.sleep(0.1)
