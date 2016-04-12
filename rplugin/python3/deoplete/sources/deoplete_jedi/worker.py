import os
import time
import queue
import logging
import threading

from .server import Client


log = logging.getLogger('deoplete.jedi')
workers = []
stop_event = threading.Event()
work_queue = queue.Queue()
comp_queue = queue.Queue()


class Worker(threading.Thread):
    daemon = True

    def __init__(self, stop, in_queue, out_queue, desc_len=0,
                 short_types=False, show_docstring=False, debug=False):
        self._client = Client(desc_len, short_types, show_docstring, debug)
        self.stop = stop
        self.in_queue = in_queue
        self.out_queue = out_queue
        super(Worker, self).__init__()
        self.log = logging.getLogger('deoplete.jedi.%s' % self.name)

    def completion_work(self, cache_key, cache_lines, extra_modules, source,
                        line, col, filename):
        completions = self._client.completions(source, line, col, filename)
        out = []
        modules = {f: int(os.path.getmtime(f)) for f in extra_modules}
        for c in completions:
            module_path, name, type_, desc, abbr, kind = c
            if module_path and module_path not in modules \
                    and os.path.exists(module_path):
                modules[module_path] = int(os.path.getmtime(module_path))

            out.append({
                '$type': type_,
                'word': name,
                'abbr': abbr,
                'kind': kind,
                'info': desc,
                'menu': '[jedi] ',
                'dup': 1,
            })

        cached = {
            'time': time.time(),
            'lines': cache_lines,
            'modules': modules,
            'completions': out,
        }

        self.out_queue.put((cache_key, cached), block=False)

    def run(self):
        try:
            while not self.stop.is_set():
                try:
                    work = self.in_queue.get(block=False, timeout=0.5)
                    self.log.debug('Got work')
                    self.completion_work(*work)
                    self.log.debug('Completed work')
                except queue.Empty:
                    # Sleep is mandatory to avoid pegging the CPU
                    time.sleep(0.01)
        except Exception:
            self.log.error('Worker error', exc_info=True)


def start(count, desc_len=0, short_types=False, show_docstring=False,
          debug=False):
    while count:
        t = Worker(stop_event, work_queue, comp_queue, desc_len, short_types,
                   show_docstring, debug)
        workers.append(t)
        t.start()
        count -= 1