"""S10 EDL builder of the webinar montage (skill video-editor, references/webinar-montage.md).

Modules: ctx (inputs, config, helpers), clock (pieces, cuts, chapter points, output clock, screen runs),
captions, feeds (slides / sketch / videos / Zoom windows, beats, marks, punch-ins, board, heroes),
events (highlight accents, raffle scene, plates), layouts (plan keyframes, cameras), chat, polls,
assemble (orchestration, post-passes, outputs). Run: python scripts/webinar/edl/build.py --job job.json [--raw]
"""
