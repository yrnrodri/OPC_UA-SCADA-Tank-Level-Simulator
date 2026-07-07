from flask import Flask, render_template, request, redirect, url_for, jsonify
from opcua import Client
import logging
import time
import threading
from threading import Event, Lock

logging.basicConfig(level=logging.WARNING)

app = Flask(__name__, static_folder='static')

# Conexão com o servidor OPC UA
client = Client("opc.tcp://localhost:4840/freeopcua/server/")
client.connect()

# Mapeamento dos nós OPC UA
# 6 nós por tanque a partir de i=7:
#   Nivel, ValvolaEntrada, ValvolaSaida, Bomba, BombaVelocidade, ModalidadeOperacional
node_ids = {
    "TanqueA": {
        "Nivel":                  "ns=2;i=7",
        "ValvolaEntrada":         "ns=2;i=8",
        "ValvolaSaida":           "ns=2;i=9",
        "Bomba":                  "ns=2;i=10",
        "BombaVelocidade":        "ns=2;i=11",
        "ModalidadeOperacional":  "ns=2;i=12",
    },
    "TanqueB": {
        "Nivel":                  "ns=2;i=13",
        "ValvolaEntrada":         "ns=2;i=14",
        "ValvolaSaida":           "ns=2;i=15",
        "Bomba":                  "ns=2;i=16",
        "BombaVelocidade":        "ns=2;i=17",
        "ModalidadeOperacional":  "ns=2;i=18",
    },
    "TanqueC": {
        "Nivel":                  "ns=2;i=19",
        "ValvolaEntrada":         "ns=2;i=20",
        "ValvolaSaida":           "ns=2;i=21",
        "Bomba":                  "ns=2;i=22",
        "BombaVelocidade":        "ns=2;i=23",
        "ModalidadeOperacional":  "ns=2;i=24",
    },
    "TanqueD": {
        "Nivel":                  "ns=2;i=25",
        "ValvolaEntrada":         "ns=2;i=26",
        "ValvolaSaida":           "ns=2;i=27",
        "Bomba":                  "ns=2;i=28",
        "BombaVelocidade":        "ns=2;i=29",
        "ModalidadeOperacional":  "ns=2;i=30",
    },
}

# Estado operacional de cada tanque (True = Automático, False = Manual)
estados_tanques = {t: True for t in node_ids}

# Flags de parada para os threads automáticos
flags_parada = {t: Event() for t in node_ids}

# Locks para sincronizar automação e operações manuais
locks = {t: Lock() for t in node_ids}


@app.route('/')
def index():
    try:
        variaveis_tanques = {}
        for tanque, variaveis in node_ids.items():
            variaveis_tanques[tanque] = {
                nome: client.get_node(no).get_value()
                for nome, no in variaveis.items()
            }
        return render_template('dashboard.html', variaveis_tanques=variaveis_tanques)
    except Exception as e:
        logging.error(f"Erro ao acessar o servidor OPC UA: {e}")
        return "Erro ao conectar ao servidor OPC UA.", 500


@app.route('/api/tanques', methods=['GET'])
def api_tanques():
    try:
        variaveis_tanques = {}
        for tanque, variaveis in node_ids.items():
            variaveis_tanques[tanque] = {
                nome: client.get_node(no).get_value()
                for nome, no in variaveis.items()
            }
            variaveis_tanques[tanque]['ModalidadeOperacional'] = estados_tanques[tanque]
        return jsonify(variaveis_tanques)
    except Exception as e:
        logging.error(f"Erro ao buscar dados dos tanques: {e}")
        return jsonify({"error": "Erro ao buscar dados"}), 500


@app.route('/<acao>_<tanque>', methods=['POST'])
def gerenciar_variavel(acao, tanque):
    try:
        with locks[tanque]:
            no_id = node_ids[tanque][acao]
            no = client.get_node(no_id)
            novo_valor = request.form['valor']

            if acao in ['ValvolaEntrada', 'ValvolaSaida', 'Bomba']:
                novo_valor = int(novo_valor)
            elif acao == 'BombaVelocidade':
                novo_valor = max(0, min(100, int(novo_valor)))
            else:
                raise ValueError(f"Ação '{acao}' inválida.")

            no.set_value(novo_valor)
            logging.info(f"Variável {acao} do {tanque} definida para {novo_valor}.")

        return redirect(url_for('index'))

    except Exception as e:
        logging.error(f"Erro ao atualizar '{acao}' do {tanque}: {e}")
        return "Erro ao atualizar o valor.", 500


@app.route('/AlterarModalidade/<tanque>', methods=['POST'])
def alterar_modalidade(tanque):
    try:
        modalidade = request.form['modalidade']
        if tanque not in estados_tanques:
            return jsonify({"error": "Tanque inválido"}), 400

        if modalidade.lower() == 'automatico':
            estados_tanques[tanque] = True
            flags_parada[tanque].clear()
            threading.Thread(target=ciclo_tanque, args=(tanque,), daemon=True).start()
            client.get_node(node_ids[tanque]["ModalidadeOperacional"]).set_value(True)
            logging.info(f"Modalidade do {tanque} definida para Automático.")
        elif modalidade.lower() == 'manual':
            estados_tanques[tanque] = False
            flags_parada[tanque].set()
            client.get_node(node_ids[tanque]["ModalidadeOperacional"]).set_value(False)
            logging.info(f"Modalidade do {tanque} definida para Manual.")
        else:
            return redirect(url_for('index'))

        return redirect(url_for('index'))

    except Exception as e:
        logging.error(f"Erro ao alterar modalidade do {tanque}: {e}")
        return jsonify({"error": "Erro ao alterar modalidade"}), 500


def ciclo_tanque(tanque):
    """
    Ciclo de controle automático do nível do tanque.

    Etapas:
      1. Reset de todos os atuadores (bomba desligada, velocidade 50 %, válvulas fechadas).
      2. Enchimento: liga a bomba (velocidade 80 %) + abre válvula de entrada → aguarda Nível >= 90 %.
      3. Esvaziamento: desliga bomba, abre válvula de saída → aguarda Nível <= 5 %.
      4. Pausa de 10 s e recomeça o ciclo.
    """
    try:
        logging.info(f"Iniciando ciclo automático do {tanque}.")
        while not flags_parada[tanque].is_set():
            valvola_entrada  = client.get_node(node_ids[tanque]["ValvolaEntrada"])
            valvola_saida    = client.get_node(node_ids[tanque]["ValvolaSaida"])
            bomba            = client.get_node(node_ids[tanque]["Bomba"])
            bomba_velocidade = client.get_node(node_ids[tanque]["BombaVelocidade"])
            nivel            = client.get_node(node_ids[tanque]["Nivel"])

            # --- Passo 1: Reset ---
            valvola_entrada.set_value(0)
            valvola_saida.set_value(0)
            bomba.set_value(0)
            bomba_velocidade.set_value(50)

            # --- Passo 2: Enchimento ---
            bomba_velocidade.set_value(80)
            bomba.set_value(1)
            valvola_entrada.set_value(1)
            while nivel.get_value() < 90.0:
                if flags_parada[tanque].is_set():
                    return
                time.sleep(1)
            valvola_entrada.set_value(0)
            bomba.set_value(0)
            bomba_velocidade.set_value(0)

            # --- Passo 3: Esvaziamento ---
            valvola_saida.set_value(1)
            while nivel.get_value() > 5.0:
                if flags_parada[tanque].is_set():
                    return
                time.sleep(1)
            valvola_saida.set_value(0)

            # --- Pausa antes de reiniciar ---
            time.sleep(10)

    except Exception as e:
        logging.error(f"Erro no ciclo do {tanque}: {e}")


# Inicia ciclos automáticos para todos os tanques na inicialização
threading.Thread(
    target=lambda: [
        threading.Thread(target=ciclo_tanque, args=(t,), daemon=True).start()
        for t in node_ids.keys()
    ],
    daemon=True
).start()

if __name__ == "__main__":
    app.run(debug=True)
