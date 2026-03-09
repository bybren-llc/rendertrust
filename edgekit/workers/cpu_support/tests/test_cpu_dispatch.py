from scheduler.cpu_filter import pick_node


class Job: pass
class Node:
    def __init__(self,id,cpu,gpu,free_cores,vram,load=0): self.id=id; self.cpu=cpu; self.gpu=gpu; self.free_cores=free_cores; self.vram=vram; self.load=load
def test_cpu_dispatch():
    job=Job(); job.requires_gpu=False; job.vram=0
    node=Node("cpu123",cpu=True,gpu=False,free_cores=8,vram=0)
    assert pick_node(job,[node]).id=="cpu123"
