import argparse

from website import create_app

app = create_app('development')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Club 360 web server')
    parser.add_argument('--host', default='127.0.0.1', help='Host to bind')
    parser.add_argument('--port', type=int, default=5000, help='Port to bind')
    args = parser.parse_args()

    app.run(debug=True, host=args.host, port=args.port)