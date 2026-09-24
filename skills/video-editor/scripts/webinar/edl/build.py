"""S10: build edl/edl.json (+ chapters, subtitles, audio plan, owner review) from the job's analysis and
edl/edl_config.json (schema: templates/edl_config.example.json).

usage: python build.py --job job.json [--raw]
  --raw   skip the post-passes sync_cams / fill_sketch_gaps (only to compare with a pre-fix reference EDL)
Then: python validate_edl.py --job job.json  ->  python split_chunks.py --job job.json
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from job import load, lower_self  # noqa: E402

load()
lower_self()
from build_edl.assemble import cli  # noqa: E402

if __name__ == '__main__':
    cli()
