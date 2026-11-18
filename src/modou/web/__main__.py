import argparse
import uvicorn
from ..logging_setup import setup
from .app import create_app

parser = argparse.ArgumentParser(description='魔豆局域网解析与在线审核')
parser.add_argument('--host', default='0.0.0.0')
parser.add_argument('--port', type=int, default=4001)
args = parser.parse_args()
setup()
uvicorn.run(create_app(), host=args.host, port=args.port, access_log=False)
