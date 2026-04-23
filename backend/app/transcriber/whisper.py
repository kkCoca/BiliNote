from faster_whisper import WhisperModel

from app.decorators.timeit import timeit
from app.models.transcriber_model import TranscriptSegment, TranscriptResult
from app.transcriber.base import Transcriber
from app.utils.env_checker import is_cuda_available, is_torch_installed
from app.utils.logger import get_logger
from app.utils.path_helper import get_model_dir

from events import transcription_finished
from pathlib import Path
import os
import shutil
import tempfile
from tqdm import tqdm
from modelscope import snapshot_download


'''
 Size of the model to use (tiny, tiny.en, base, base.en, small, small.en, distil-small.en, medium, medium.en, distil-medium.en, large-v1, large-v2, large-v3, large, distil-large-v2, distil-large-v3, large-v3-turbo, or turbo
'''
logger=get_logger(__name__)

MODEL_MAP={
    "tiny": "pengzhendong/faster-whisper-tiny",
    'base':'pengzhendong/faster-whisper-base',
    'small':'pengzhendong/faster-whisper-small',
    'medium':'pengzhendong/faster-whisper-medium',
    'large-v1':'pengzhendong/faster-whisper-large-v1',
    'large-v2':'pengzhendong/faster-whisper-large-v2',
    'large-v3':'pengzhendong/faster-whisper-large-v3',
    'large-v3-turbo':'pengzhendong/faster-whisper-large-v3-turbo',
}

class WhisperTranscriber(Transcriber):
    # TODO:修改为可配置
    def __init__(
            self,
            model_size: str = "base",
            device: str = 'cpu',
            compute_type: str = None,
            cpu_threads: int = 1,
    ):
        if device == 'cpu' or device is None:
            self.device = 'cpu'
        else:
            self.device = "cuda" if self.is_cuda() else "cpu"
            if device == 'cuda' and self.device == 'cpu':
                print('没有 cuda 使用 cpu进行计算')

        self.compute_type = compute_type or ("float16" if self.device == "cuda" else "int8")

        model_dir = get_model_dir("whisper")
        model_path = os.path.join(model_dir, f"whisper-{model_size}")
        # `faster_whisper` needs model artifacts like `model.bin`. The directory can exist but be incomplete
        # (e.g. interrupted download). Treat that as missing and re-download.
        required_files = [Path(model_path) / "model.bin"]
        repo_id = MODEL_MAP.get(model_size)
        if not repo_id:
            raise ValueError(
                f"不支持的 whisper model_size: {model_size}，支持: {', '.join(MODEL_MAP.keys())}"
            )

        def _download_model_atomic() -> None:
            logger.info(f"模型 whisper-{model_size} 不存在或不完整，开始下载...")
            # Remove the target dir first to avoid other requests picking up a known-bad/incomplete model.
            shutil.rmtree(model_path, ignore_errors=True)
            tmp_dir = tempfile.mkdtemp(dir=model_dir, prefix=f".whisper-{model_size}-")
            try:
                # Download into a temp dir then rename into place to avoid partial/corrupt directories.
                snapshot_download(
                    repo_id,
                    local_dir=tmp_dir,
                    max_workers=1,
                )

                # Validate required files (ctranslate2 Whisper needs vocabulary/tokenizer too).
                if not (Path(tmp_dir) / "model.bin").exists():
                    raise RuntimeError("模型下载失败: 未找到 model.bin")
                vocab_ok = any(
                    (Path(tmp_dir) / n).exists()
                    for n in ("vocabulary.json", "vocabulary.txt", "vocab.json", "vocab.txt")
                )
                tok_ok = any((Path(tmp_dir) / n).exists() for n in ("tokenizer.json", "tokenizer.model"))
                if not (vocab_ok and tok_ok):
                    raise RuntimeError("模型下载不完整: 缺少 vocabulary/tokenizer 文件")

                shutil.rmtree(model_path, ignore_errors=True)
                shutil.move(tmp_dir, model_path)
                logger.info("模型下载完成")
            except Exception:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                raise

        # model.bin plus vocabulary/tokenizer must exist.
        vocab_ok = any(
            (Path(model_path) / n).exists()
            for n in ("vocabulary.json", "vocabulary.txt", "vocab.json", "vocab.txt")
        )
        tok_ok = any((Path(model_path) / n).exists() for n in ("tokenizer.json", "tokenizer.model"))

        if not (all(p.exists() for p in required_files) and vocab_ok and tok_ok):
            _download_model_atomic()

        try:
            self.model = WhisperModel(
                model_size_or_path=model_path,
                device=self.device,
                compute_type=self.compute_type,
                download_root=model_dir,
            )
        except RuntimeError as e:
            # Corrupt/incomplete model happens with interrupted downloads; re-download once.
            if "model.bin" in str(e) and "incomplete" in str(e):
                logger.warning(f"检测到模型文件不完整，重新下载: {e}")
                _download_model_atomic()
                self.model = WhisperModel(
                    model_size_or_path=model_path,
                    device=self.device,
                    compute_type=self.compute_type,
                    download_root=model_dir,
                )
            else:
                raise
    @staticmethod
    def is_torch_installed() -> bool:
        try:
            import torch
            return True
        except ImportError:
            return False

    @staticmethod
    def is_cuda() -> bool:
        try:
            if is_cuda_available():
                print(" CUDA 可用，使用 GPU")
                return True
            elif is_torch_installed():
                print(" 只装了 torch，但没有 CUDA，用 CPU")
                return False
            else:
                print(" 还没有安装 torch，请先安装")
                return False

        except ImportError:
            return False

    @timeit
    def transcript(self, file_path: str) -> TranscriptResult:
        segments_raw, info = self.model.transcribe(file_path)

        segments = []
        full_text = ""

        for seg in segments_raw:
            text = seg.text.strip()
            full_text += text + " "
            segments.append(
                TranscriptSegment(
                    start=seg.start,
                    end=seg.end,
                    text=text,
                )
            )

        result = TranscriptResult(
            language=info.language,
            full_text=full_text.strip(),
            segments=segments,
            raw=info,
        )
        return result


    def on_finish(self,video_path:str,result: TranscriptResult)->None:
        print("转写完成")
        transcription_finished.send({
            "file_path": video_path,
        })
