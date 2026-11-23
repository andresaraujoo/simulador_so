"""Testes adicionais da Etapa 4: execute na raiz do projeto com
python testes_etapa4_auditoria.py

Arquivo independente: NAO altera os modulos da equipe. As 3 verificacoes
marcadas com expectedFailure documentam pontos que requerem revisao.
"""
import io
import unittest
from contextlib import redirect_stdout

from fs_simulador.memory_manager import MemoryManager
from fs_simulador.filesystem import FileSystem


class TestesEtapa4(unittest.TestCase):
    def setUp(self):
        self.mem = MemoryManager()
        self.saida = io.StringIO()
        self.redirecionar = redirect_stdout(self.saida)
        self.redirecionar.__enter__()

    def tearDown(self):
        self.redirecionar.__exit__(None, None, None)

    def test_exemplo_4_1_fragmentacao_compactacao(self):
        m = self.mem
        m.create_process("DiskDriver", 512 * 1024, "critical")
        m.create_process("NetDriver", 1024 * 1024, "critical")
        m.create_process("CryptoEngine", 512 * 1024, "critical")
        m.terminate_process("NetDriver")
        self.assertEqual(m.reserved.get_fragmentation_metrics(), (2048, 1024, 2))
        with self.assertRaises(MemoryError):
            m.create_process("Grande", 1536 * 1024, "critical")
        m.compact_reserved()
        self.assertEqual(m.reserved.get_fragmentation_metrics(), (2048, 2048, 1))
        m.create_process("Grande", 1536 * 1024, "critical")

    def test_exemplo_4_2_paginacao(self):
        m = self.mem
        m.create_process("App", 10 * 1024)
        p = m.virtual.processes["App"]
        self.assertEqual(p["num_pages"], 3)
        self.assertEqual(p["internal_frag"], 2048)
        self.assertTrue(all(not e["present"] for e in p["page_table"].values()))

    def test_traducao_miss_e_hit(self):
        m = self.mem
        m.create_process("App", 10 * 1024)
        self.assertIsNone(m.translate_address("App", 1))
        self.assertEqual(m.execute_step("App", "LOAD_DATA Página 1")["frame"], 88)
        self.assertEqual(m.translate_address("App", 1), 88)

    def test_lru_troca_pagina_mais_antiga(self):
        m = self.mem
        m.create_process("App", 10 * 1024)
        m.execute_step("App", "LOAD_DATA Página 1")
        self.assertEqual(m.execute_step("App", "LOAD_DATA Página 2")["frame"], 12)
        daemon = m.virtual.processes["PID_102_SystemDaemon"]
        self.assertFalse(daemon["page_table"][0]["present"])

    def test_lru_respeita_acesso_recente(self):
        m = self.mem
        m.create_process("App", 10 * 1024)
        for p in (1, 2, 1, 0):
            m.execute_step("App", f"LOAD_DATA Página {p}")
        self.assertTrue(m.virtual.processes["App"]["page_table"][1]["present"])
        self.assertFalse(m.virtual.processes["PID_102_SystemDaemon"]["page_table"][1]["present"])

    def test_segunda_chance(self):
        m = self.mem
        m.virtual.set_algorithm("SECOND_CHANCE")
        m.create_process("App", 10 * 1024)
        m.execute_step("App", "LOAD_DATA Página 1")
        for entrada in m.virtual.frames.values():
            entrada["ref_bit"] = 1
        r = m.execute_step("App", "LOAD_DATA Página 2")
        self.assertEqual(r["status"], "PAGE_FAULT")
        self.assertEqual(r["frame"], 12)

    def test_contadores_e_pagina_invalida(self):
        m = self.mem
        m.create_process("App", 4096)
        with self.assertRaises(ValueError):
            m.execute_step("App", "LOAD_DATA Página 100")
        m.execute_step("App", "LOAD_DATA Página 0")
        m.execute_step("App", "LOAD_DATA Página 0")
        self.assertEqual((m.virtual.page_hits, m.virtual.page_faults), (1, 1))

    def test_swap_gera_requisicoes_es(self):
        fs = FileSystem()
        chamadas = []
        fs.perform_io = lambda operacao, blocos: chamadas.append(operacao)
        m = MemoryManager(filesystem=fs)
        m.create_process("App", 10 * 1024)
        m.execute_step("App", "LOAD_DATA Página 1")
        m.execute_step("App", "LOAD_DATA Página 2")
        self.assertEqual(chamadas, ["SWAP_IN", "SWAP_OUT", "SWAP_IN"])

    # Erros identificados: os 3 testes abaixo so passarao apos correcoes.
    @unittest.expectedFailure
    def test_pendente_tamanho_critico_1025_bytes(self):
        m = self.mem
        m.create_process("Critico", 1025, "critical")
        bloco = next(b for b in m.reserved.blocks if b["process"] == "Critico")
        self.assertGreaterEqual(bloco["size"] * 1024, 1025)

    @unittest.expectedFailure
    def test_pendente_rejeitar_critico_zero_bytes(self):
        with self.assertRaises(ValueError):
            self.mem.create_process("Zero", 0, "critical")

    @unittest.expectedFailure
    def test_pendente_swap_persiste_paginas_no_disco(self):
        fs = FileSystem()
        m = MemoryManager(filesystem=fs)
        m.create_process("App", 4096)
        m.execute_step("App", "LOAD_DATA Página 0")
        # Este modulo atualmente apenas simula movimento, sem persistir paginas.
        self.assertTrue(any(b and b.get("type") == "SWAP" for b in fs.disk.blocks))


if __name__ == "__main__":
    unittest.main(verbosity=2)
