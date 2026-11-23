import re
from fs_simulador.reserved_memory import ReservedMemory
from fs_simulador.virtual_memory import VirtualMemory


class MemoryManager:
    """
    Controlador Híbrido de Memória (Etapa 4).
    Integra Área Reservada (Contígua), Memória Virtual (Paginada) e E/S de Swap com o Disco.
    """

    def __init__(self, filesystem=None):
        self.filesystem = filesystem
        self.reserved = ReservedMemory(total_kb=4096)
        self.virtual = VirtualMemory(page_size=4096, frame_pool=[12, 45, 73, 88])
        self.next_pid = 103
        self.process_registry = {}  # name -> {"pid": int, "type": "critical"|"normal"}
        # Cada pagina usa um bloco de disco exclusivo: sem hash ou colisao.
        self.swap_blocks = {}  # (nome_processo, pagina) -> bloco fisico

    def create_process(self, name, size_bytes, proc_type="normal"):
        if type(size_bytes) is not int or size_bytes <= 0:
            raise ValueError("O tamanho do processo deve ser um inteiro positivo em bytes.")
        proc_type = proc_type.lower()
        if name in self.process_registry:
            raise ValueError(f"Já existe um processo chamado '{name}'.")

        pid = self.next_pid
        if proc_type == "critical":
            # Arredonda para CIMA: 1025 bytes necessitam de 2 KB.
            size_kb = (size_bytes + 1023) // 1024
            self.reserved.allocate(name, size_kb)
            self.process_registry[name] = {"pid": pid, "type": "critical"}
        elif proc_type == "normal":
            self.virtual.create_process(name, size_bytes, pid)
            self.process_registry[name] = {"pid": pid, "type": "normal"}
        else:
            raise ValueError("Tipo de processo inválido. Use 'critical' ou 'normal'.")

        self.next_pid += 1

    def terminate_process(self, name):
        if name not in self.process_registry:
            raise ValueError(f"Processo '{name}' não encontrado.")

        info = self.process_registry.pop(name)
        if info["type"] == "critical":
            self.reserved.deallocate(name)
        else:
            self.virtual.terminate_process(name)
            # Libera os blocos de swap pertencentes ao processo finalizado.
            if self.filesystem:
                slots = [key for key in self.swap_blocks if key[0] == name]
                self.filesystem.disk.release([self.swap_blocks[key] for key in slots])
                for key in slots:
                    del self.swap_blocks[key]

    def _handle_swap_io(self, direction, process_name, page_num, content=None):
        """Aloca um bloco fisico exclusivo, persiste bytes e registra a E/S."""
        if not self.filesystem:
            return None
        disk = self.filesystem.disk
        if self.virtual.page_size != disk.block_size:
            raise ValueError("Nesta simulacao, pagina e bloco de swap devem ter o mesmo tamanho.")

        key = (process_name, page_num)
        if key not in self.swap_blocks:
            # Reserva bloco do disco; nao reutiliza blocos de arquivos normais.
            block_index = disk.allocate(1, self.filesystem.root, "SWAP")[0]
            self.swap_blocks[key] = block_index
            disk.blocks[block_index].update({
                "process": process_name,
                "page": page_num,
                "content": bytes(self.virtual.page_size),
            })

        block_index = self.swap_blocks[key]
        block = disk.blocks[block_index]
        if direction == "SWAP_OUT":
            if not isinstance(content, bytes) or len(content) != self.virtual.page_size:
                raise ValueError("SWAP_OUT exige o conteudo completo de uma pagina em bytes.")
            block["content"] = content
        elif direction != "SWAP_IN":
            raise ValueError("Operacao de swap desconhecida.")

        print(
            f"[SWAP -> DISCO] {direction}: pagina {page_num} de '{process_name}', "
            f"bloco {block_index}, {len(block['content'])} bytes."
        )
        self.filesystem.perform_io(direction, [block_index])
        # SWAP_IN devolve os bytes efetivamente gravados no bloco de disco.
        return block["content"] if direction == "SWAP_IN" else None

    def translate_address(self, process_name, page_num):
        return self.virtual.translate_address(process_name, page_num)

    def execute_step(self, process_name, instruction):
        """Interpreta instruções como 'LOAD_DATA Página 2' e referencia a página na memória."""
        match = re.search(r"(\d+)", instruction)
        if not match:
            raise ValueError("Instrução deve informar o número da página (ex: 'LOAD_DATA Página 2').")

        page_num = int(match.group(1))
        return self.virtual.access_page(
            process_name,
            page_num,
            instruction=instruction,
            swap_callback=self._handle_swap_io,
        )

    def compact_reserved(self):
        self.reserved.compact()

    def show_status(self, mode="all"):
        if mode == "reserved":
            self.reserved.show_status()
        elif mode == "virtual":
            self.virtual.show_status()
        else:
            self.reserved.show_status()
            self.virtual.show_status()