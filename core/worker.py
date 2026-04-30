from PySide6.QtCore import QObject, QRunnable, Signal, Slot
import traceback
import sys

class WorkerSignals(QObject):
    """
    Workerスレッドから発行されるシグナルを定義するクラス。
    """
    finished = Signal()
    error = Signal(tuple) # (exctype, value, traceback.format_exc())
    result = Signal(object)
    progress = Signal(int)

class Worker(QRunnable):
    """
    汎用的なWorkerクラス。任意の関数をスレッドプールで実行します。
    """
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        """
        スレッドプールから呼び出されるメイン処理。
        """
        try:
            result = self.fn(*self.args, **self.kwargs)
        except:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        else:
            self.signals.result.emit(result)
        finally:
            self.signals.finished.emit()
