from opcua import Server
from datetime import datetime
import time
from opcua import ua

# Criação do servidor OPC UA
server = Server()
server.set_endpoint("opc.tcp://0.0.0.0:4840/freeopcua/server/")

# Namespace URI
uri = "http://example.org/controle_tanques"
idx = server.register_namespace(uri)

# Objeto raiz
contexto_industrial = server.nodes.objects.add_object(idx, "ContextoIndustrial")
servidor_unico = contexto_industrial.add_object(idx, "ServidorUnico")

# Criação dos Tanques
tanqueA = servidor_unico.add_object(idx, "TanqueA")
tanqueB = servidor_unico.add_object(idx, "TanqueB")
tanqueC = servidor_unico.add_object(idx, "TanqueC")
tanqueD = servidor_unico.add_object(idx, "TanqueD")

# Função para criar as variáveis de cada tanque
# Variáveis por tanque (6 nós cada):
#   Nivel, ValvolaEntrada, ValvolaSaida, Bomba, BombaVelocidade, ModalidadeOperacional
def adicionar_variaveis_tanque(nome_pai, tanque, nivel):
    nivel_var = tanque.add_variable(idx, f"{nome_pai}_Nivel", round(nivel, 1), datatype=ua.NodeId(ua.ObjectIds.Double))
    nivel_var.set_writable()
    print(f"Nó criado: {nome_pai}_Nivel -> {nivel_var.nodeid}")

    valvola_entrada_var = tanque.add_variable(idx, f"{nome_pai}_ValvolaEntrada", 0, datatype=ua.NodeId(ua.ObjectIds.Int32))
    valvola_entrada_var.set_writable()
    print(f"Nó criado: {nome_pai}_ValvolaEntrada -> {valvola_entrada_var.nodeid}")

    valvola_saida_var = tanque.add_variable(idx, f"{nome_pai}_ValvolaSaida", 0, datatype=ua.NodeId(ua.ObjectIds.Int32))
    valvola_saida_var.set_writable()
    print(f"Nó criado: {nome_pai}_ValvolaSaida -> {valvola_saida_var.nodeid}")

    bomba_var = tanque.add_variable(idx, f"{nome_pai}_Bomba", 0, datatype=ua.NodeId(ua.ObjectIds.Int32))
    bomba_var.set_writable()
    print(f"Nó criado: {nome_pai}_Bomba -> {bomba_var.nodeid}")

    # Velocidade da bomba em % (0–100). Determina a taxa de enchimento.
    bomba_velocidade_var = tanque.add_variable(idx, f"{nome_pai}_BombaVelocidade", 50, datatype=ua.NodeId(ua.ObjectIds.Int32))
    bomba_velocidade_var.set_writable()
    print(f"Nó criado: {nome_pai}_BombaVelocidade -> {bomba_velocidade_var.nodeid}")

    modalidade_var = tanque.add_variable(idx, f"{nome_pai}_ModalidadeOperacional", True, datatype=ua.NodeId(ua.ObjectIds.Boolean))
    modalidade_var.set_writable()
    print(f"Nó criado: {nome_pai}_ModalidadeOperacional -> {modalidade_var.nodeid}")

    return nivel_var, valvola_entrada_var, valvola_saida_var, bomba_var, bomba_velocidade_var, modalidade_var


# Adiciona variáveis aos Tanques com níveis iniciais distintos
variaveis_tanqueA = adicionar_variaveis_tanque("TanqueA", tanqueA, 8.0)
variaveis_tanqueB = adicionar_variaveis_tanque("TanqueB", tanqueB, 9.0)
variaveis_tanqueC = adicionar_variaveis_tanque("TanqueC", tanqueC, 6.0)
variaveis_tanqueD = adicionar_variaveis_tanque("TanqueD", tanqueD, 7.0)

# Limites do nível (em %)
NIVEL_MIN, NIVEL_MAX = 0.0, 100.0

# Taxa base de enchimento/esvaziamento por ciclo de 5 s (em % absoluta do nível)
# A taxa real de enchimento é proporcional à velocidade da bomba (0–100%).
TAXA_SAIDA = 0.025   # 2,5 % do nível atual por ciclo (saída é sempre fixa pela gravidade)


def atualizar_variaveis(tanque_vars):
    nivel, valvola_entrada, valvola_saida, bomba, bomba_velocidade, modalidade = tanque_vars

    nivel_atual        = nivel.get_value()
    bomba_ligada       = bomba.get_value() == 1
    velocidade_pct     = max(0, min(100, bomba_velocidade.get_value()))  # clamp 0-100
    valv_entrada_aberta = valvola_entrada.get_value() == 1
    valv_saida_aberta   = valvola_saida.get_value() == 1

    # Taxa de enchimento proporcional à velocidade da bomba
    # Máximo (+10 % do nível atual / ciclo a 100 % de velocidade)
    taxa_entrada = 2 * TAXA_SAIDA * (velocidade_pct / 100.0)

    if bomba_ligada and valv_entrada_aberta:
        incremento = (nivel_atual * taxa_entrada) if nivel_atual > 0 else (2.0 * taxa_entrada)
        novo_nivel = nivel_atual + incremento

        if valv_saida_aberta:
            novo_nivel -= (nivel_atual * TAXA_SAIDA)
            
    elif valv_saida_aberta:
        novo_nivel = nivel_atual - (nivel_atual * TAXA_SAIDA)
    else:
        novo_nivel = nivel_atual

    novo_nivel = round(min(max(novo_nivel, NIVEL_MIN), NIVEL_MAX), 1)
    nivel.set_value(novo_nivel)


# Handler de log para mudanças OPC-UA
class LogHandler:
    def datachange_notification(self, node, val, data):
        print(f"[{datetime.now()}] Mudança de Dado: Nó: {node}, Valor: {val}")


# Inicia o servidor
server.start()

try:
    print(f"Servidor OPC UA iniciado em {server.endpoint}")
    print("Namespaces registrados:", server.get_namespace_array())

    handler = LogHandler()
    subscription = server.create_subscription(500, handler)

    for variaveis in [variaveis_tanqueA, variaveis_tanqueB, variaveis_tanqueC, variaveis_tanqueD]:
        for var in variaveis:
            subscription.subscribe_data_change(var)

    # Loop principal: atualiza a cada 5 segundos
    while True:
        for i, tanque_vars in enumerate([variaveis_tanqueA, variaveis_tanqueB, variaveis_tanqueC, variaveis_tanqueD]):
            print(f"Atualizando variáveis do Tanque {chr(65+i)}...")
            atualizar_variaveis(tanque_vars)
        time.sleep(5)

except KeyboardInterrupt:
    print("Encerrando o servidor OPC UA...")
finally:
    server.stop()
    print("Servidor encerrado.")
