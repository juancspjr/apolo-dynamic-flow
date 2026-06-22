from http.server import BaseHTTPRequestHandler, HTTPServer
import json

class HookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        longitud = int(self.headers['Content-Length'])
        datos = self.rfile.read(longitud)
        
        print("\n" + "="*40)
        print("💥 ¡HOOK RECIBIDO DESDE OPENCODE! 💥")
        print("="*40)
        
        evento = self.headers.get('X-Gitlab-Event', 'Desconocido')
        print(f"Tipo de evento: {evento}\n")
        
        try:
            json_datos = json.loads(datos.decode('utf-8'))
            print(json.dumps(json_datos, indent=2))
        except Exception as e:
            print(f"Error al leer JSON: {e}")
            print(datos.decode('utf-8'))
            
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.end_headers()
        self.wfile.write(b"OK")

puerto = 8000
servidor = HTTPServer(('0.0.0.0', puerto), HookHandler)
print(f"Escuchando hooks de OpenCoDE en el puerto {puerto}...")
print("Presiona Ctrl+C para salir.")
servidor.serve_forever()
