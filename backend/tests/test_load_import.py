"""
Load test per import massivo (RF1/RF1b)
Misura tempi di upload/elaborazione con 50, 100, 200, 300 file
"""
import asyncio
import time
import sys
from pathlib import Path
from PIL import Image
import uuid
import tempfile
import shutil

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.pipeline import state as state_store


async def run_pipeline(file_count: int):
    """Misura tempo intake+normalizer+sequence per N file"""
    from app.agents.intake import run as intake_run
    from app.agents.normalizer import run as normalizer_run
    from app.agents.sequence import run as sequence_run
    
    project_id = f"load_test_{uuid.uuid4().hex[:8]}"
    
    try:
        # Setup progetto
        proj_dir = state_store.project_dir(project_id)
        proj_dir.mkdir(parents=True, exist_ok=True)
        
        # Crea file
        media_dir = state_store.media_dir(project_id)
        files = create_test_images(file_count, media_dir)
        
        # Simula staging
        staging = [{"path": str(f), "source": "local", "drive_file_id": None} for f in files]
        
        state = {
            "project_id": project_id,
            "media_staging": staging,
            "media": [],
            "sequence": [],
            "settings": {"duration_per_photo": 5.0, "transition_duration": 0.8}
        }
        
        # Misura tempi
        start = time.time()
        
        t0 = time.time()
        state = await intake_run(state)
        t1 = time.time() - t0
        
        t0 = time.time()
        state = await normalizer_run(state)
        t1_norm = time.time() - t0
        
        t0 = time.time()
        state = await sequence_run(state)
        t1_seq = time.time() - t0
        
        total = time.time() - start
        
        return {
            "files": file_count,
            "intake_sec": round(t1, 3),
            "normalizer_sec": round(t1_norm, 3),
            "sequence_sec": round(t1_seq, 3),
            "total_sec": round(total, 3),
            "media_count": len(state.get("media", [])),
            "sequence_count": len(state.get("sequence", []))
        }
    finally:
        # Cleanup
        shutil.rmtree(state_store.project_dir(project_id), ignore_errors=True)


def create_test_images(count: int, dest_dir: Path):
    """Crea N immagini finte"""
    dest_dir.mkdir(exist_ok=True)
    for i in range(count):
        img = Image.new('RGB', (1920, 1080), color=(i % 256, (i * 2) % 256, (i * 3) % 256))
        img.save(dest_dir / f'{uuid.uuid4().hex[:8]}.jpg', 'JPEG')
    return list(dest_dir.glob('*.jpg'))


if __name__ == "__main__":
    print("=== Load Test: Import Massivo (RF1/RF1b) ===\n")
    print(f"{'File':<6} | {'Intake':<8} | {'Normalizer':<10} | {'Sequence':<9} | {'Totale':<8} | {'Media':<6} | {'Seq':<4}")
    print("-" * 75)
    
    for count in [50, 100, 200, 300]:
        result = asyncio.run(run_pipeline(count))
        print(f"{result['files']:<6} | {result['intake_sec']:<8.3f} | {result['normalizer_sec']:<10.3f} | "
              f"{result['sequence_sec']:<9.3f} | {result['total_sec']:<8.3f} | {result['media_count']:<6} | {result['sequence_count']:<4}")
    
    print("\nNota: Tempi >5s richiedono background=true per non bloccare UI")
