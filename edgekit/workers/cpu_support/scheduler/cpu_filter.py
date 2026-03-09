def pick_node(job, nodes):
    if job.requires_gpu:
        candidates = [n for n in nodes if n.gpu and n.vram >= job.vram]
    else:
        candidates = [n for n in nodes if n.cpu and n.free_cores >= 4]
    return sorted(candidates, key=lambda n: n.load)[0] if candidates else None
