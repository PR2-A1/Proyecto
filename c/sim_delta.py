"""
Simulador del robot Delta.
Escucha giirob/pr2-A1/devices/robodk/action y responde automáticamente
con un completed en giirob/pr2-A1/devices/delta/status al recibir un spawn.
También permite enviar tapas manuales desde el menú.
"""

import json
import time
import threading
import paho.mqtt.client as mqtt

BROKER        = "broker.hivemq.com"
PORT          = 1883
TOPIC_SPAWN   = "giirob/pr2-A1/devices/robodk/action"
TOPIC_DELTA   = "giirob/pr2-A1/devices/delta/status"
COLORS        = ["red", "yellow", "green", "white", "orange", "blue"]

# Delay en segundos entre recibir spawn y enviar completed (simula tiempo del delta)
DELTA_DELAY = 1.5

cap_counter_lock = threading.Lock()
cap_counter = 0

def next_id_cap():
    global cap_counter
    with cap_counter_lock:
        cap_counter += 1
        return f"C{cap_counter:04d}"

def send_completed(client, color: str, id_cap: str):
    payload = json.dumps({
        "status": "completed",
        "color":  color,
        "id_cap": id_cap,
    })
    client.publish(TOPIC_DELTA, payload, qos=1)
    print(f"  [delta ->] {payload}")

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"Conectado a {BROKER}:{PORT}")
        client.subscribe(TOPIC_SPAWN, qos=1)
        print(f"Suscrito a {TOPIC_SPAWN}")
    else:
        print(f"Error de conexión: rc={rc}")

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
    except Exception:
        return

    if msg.topic == TOPIC_SPAWN and data.get("cmd") == "spawn":
        color  = data.get("color", "red")
        id_cap = data.get("id_cap", next_id_cap())
        print(f"  [spawn <-] id_cap={id_cap} color={color}  (respondiendo en {DELTA_DELAY}s)")
        def reply():
            time.sleep(DELTA_DELAY)
            send_completed(client, color, id_cap)
        threading.Thread(target=reply, daemon=True).start()

def menu():
    print("\n=== Simulador Delta ===")
    print("  [auto] Responde automáticamente a cada spawn recibido")
    for i, c in enumerate(COLORS, 1):
        print(f"  {i}. Enviar tapa manual: {c}")
    print("  d. Cambiar delay de respuesta")
    print("  q. Salir")
    return input("Opción: ").strip().lower()

def main():
    global DELTA_DELAY

    client = mqtt.Client(client_id="sim_delta_py")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER, PORT, keepalive=60)
    client.loop_start()

    while True:
        opt = menu()

        if opt == "q":
            break

        if opt == "d":
            try:
                DELTA_DELAY = float(input(f"  Delay actual: {DELTA_DELAY}s  Nuevo valor (s): "))
                print(f"  Delay actualizado a {DELTA_DELAY}s")
            except ValueError:
                print("  Valor inválido.")
            continue

        try:
            idx = int(opt) - 1
            if 0 <= idx < len(COLORS):
                color  = COLORS[idx]
                id_cap = next_id_cap()
                send_completed(client, color, id_cap)
            else:
                print("  Opción fuera de rango.")
        except ValueError:
            print("  Opción no reconocida.")

    client.loop_stop()
    client.disconnect()
    print("Desconectado.")

if __name__ == "__main__":
    main()
