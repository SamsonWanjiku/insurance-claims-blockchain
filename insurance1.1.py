import hashlib
import json
from textwrap import dedent
from uuid import uuid4
from flask import Flask, jsonify, request
from urllib.parse import urlparse
from Crypto.PublicKey import RSA
from Crypto.Signature import *
from time import time
from datetime import datetime
import requests


class Blockchain(object):
    def __init__(self):
        self.chain = [self.create_genesis_block()]
        self.pending_transactions = []
        self.difficulty = 2
        self.miner_rewards = 50
        self.block_size = 10
        self.nodes = set()

    def register_node(self, address):
        parsed_url = urlparse(address)
        self.nodes.add(parsed_url.netloc)

    def resolve_conflicts(self):
        neighbors = self.nodes
        new_chain = None

        max_length = len(self.chain)

        for node in neighbors:
            response = requests.get(f'http://{node}/chain')

            if response.status_code == 200:
                length = response.json()['length']
                chain = response.json()['chain']

                if length > max_length and self.is_valid_chain(chain):
                    max_length = length
                    new_chain = chain

        if new_chain:
            self.chain = self.decode_chain(new_chain)
            return True

        return False

    def mine_pending_transactions(self, miner):
        len_pending_transactions = len(self.pending_transactions)

        if len_pending_transactions <= 1:
            raise Exception("Not enough transactions to mine! (Must be > 1)")

        for i in range(0, len_pending_transactions, self.block_size):
            end = i + self.block_size
            if i >= len_pending_transactions:
                end = len_pending_transactions

            transaction_slice = self.pending_transactions[i:end]

            new_block = Block(transaction_slice, datetime.now().strftime("%m/%d/%Y, %H:%M:%S"), len(self.chain))
            new_block.previous_hash = self.get_last_block().hash
            new_block.mine_block(self.difficulty)

            self.chain.append(new_block)

        self.pending_transactions = [Transaction("Miner Rewards", miner, self.miner_rewards)]

        return True

    def add_transaction(self, sender, receiver, amount, key_string, sender_key):
        key_byte = key_string.encode("ASCII")
        sender_key_byte = sender_key.encode("ASCII")

        key = RSA.import_key(key_byte)
        sender_key = RSA.import_key(sender_key_byte)

        if not sender or not receiver or not amount:
            raise Exception("Invalid transaction")

        transaction = Transaction(sender, receiver, amount)
        transaction.sign_transaction(key, sender_key)

        if not transaction.is_valid_transaction():
            raise Exception("Invalid transaction")

        self.pending_transactions.append(transaction)
        return len(self.chain) + 1

    def get_last_block(self):
        return self.chain[-1]

    def create_genesis_block(self):
        t_arr = []
        t_arr.append(Transaction("me", "you", 10))
        genesis = Block(t_arr, datetime.now().strftime("%m/%d/%Y, %H:%M:%S"), 0)
        genesis.previous_hash = "None"
        return genesis

    def is_valid_chain(self, chain):
        previous_block = chain[0]
        current_index = 1

        while current_index < len(chain):
            block = chain[current_index]

            if not block.has_valid_transactions():
                return False

            if block.hash != block.calculate_hash():
                return False

            if block.previous_hash != previous_block.hash:
                return False

            previous_block = block
            current_index += 1

        return True

    def decode_chain(self, chain_json):
        decoded_chain = []
        for block_json in chain_json:
            transactions = []
            for transaction_json in block_json['transactions']:
                transactions.append(Transaction(transaction_json['sender'], transaction_json['receiver'], transaction_json['amount'], transaction_json['signature'], transaction_json['timestamp']))

            block = Block(transactions, block_json['timestamp'], block_json['index'])
            block.previous_hash = block_json['previous_hash']
            block.hash = block_json['hash']

            decoded_chain.append(block)

        return decoded_chain


class Block(object):
    def __init__(self, transactions, timestamp, index):
        self.index = index
        self.timestamp = timestamp
        self.transactions = transactions
        self.previous_hash = ""
        self.nonce = 0
        self.hash = self.calculate_hash()

    def calculate_hash(self):
        block_string = f"{self.index}{self.previous_hash}{self.timestamp}{json.dumps([tx.to_dict() for tx in self.transactions])}{self.nonce}"
        return hashlib.sha256(block_string.encode()).hexdigest()

    def mine_block(self, difficulty):
        while self.hash[:difficulty] != "0" * difficulty:
            self.nonce += 1
            self.hash = self.calculate_hash()

    def has_valid_transactions(self):
        for transaction in self.transactions:
            if not transaction.is_valid_transaction():
                return False
        return True


class Transaction(object):
    def __init__(self, sender, receiver, amount, signature=None, timestamp=None):
        self.sender = sender
        self.receiver = receiver
        self.amount = amount
        self.signature = signature
        self.timestamp = timestamp if timestamp else time()

    def calculate_hash(self):
        transaction_string = f"{self.sender}{self.receiver}{self.amount}{self.timestamp}"
        return hashlib.sha256(transaction_string.encode()).hexdigest()

    def sign_transaction(self, private_key, sender_key):
        if self.sender == "Miner Rewards":
            return

        if sender_key.publickey().export_key().decode("ASCII") != private_key.publickey().export_key().decode("ASCII"):
            raise Exception("You cannot sign transactions for other senders!")

        hash_tx = self.calculate_hash()
        signer = PKCS1_v1_5.new(private_key)
        self.signature = signer.sign(hash_tx.encode())

    def is_valid_transaction(self):
        if self.sender == "Miner Rewards":
            return True

        if not self.signature:
            raise Exception("Transaction is not signed!")

        sender_key = RSA.import_key(self.sender.encode("ASCII"))
        hash_tx = self.calculate_hash()
        verifier = PKCS1_v1_5.new(sender_key)

        return verifier.verify(hash_tx.encode(), self.signature)

    def to_dict(self):
        return {
            "sender": self.sender,
            "receiver": self.receiver,
            "amount": self.amount,
            "signature": self.signature.hex() if self.signature else None,
            "timestamp": self.timestamp
        }


# Create the Flask application
app = Flask(__name__)

# Generate a globally unique address for this node
node_identifier = str(uuid4()).replace('-', '')

# Create the blockchain
blockchain = Blockchain()


@app.route('/mine', methods=['GET'])
def mine():
    miner = node_identifier
    if len(blockchain.pending_transactions) == 0:
        return jsonify({'message': 'No transactions to mine'}), 400

    if blockchain.mine_pending_transactions(miner):
        response = {
            'message': 'New block mined',
            'index': blockchain.get_last_block().index,
            'transactions': [tx.to_dict() for tx in blockchain.get_last_block().transactions],
            'timestamp': blockchain.get_last_block().timestamp,
            'previous_hash': blockchain.get_last_block().previous_hash,
            'hash': blockchain.get_last_block().hash
        }
        return jsonify(response), 200
    else:
        return jsonify({'message': 'Mining failed'}), 500


@app.route('/transactions/new', methods=['POST'])
def new_transaction():
    values = request.get_json()
    required_fields = ['sender', 'receiver', 'amount', 'signature', 'sender_key']

    if not all(field in values for field in required_fields):
        return jsonify({'message': 'Missing fields in transaction'}), 400

    try:
        index = blockchain.add_transaction(values['sender'], values['receiver'], values['amount'], values['signature'], values['sender_key'])
        response = {'message': f'Transaction will be added to Block {index}'}
        return jsonify(response), 201
    except Exception as e:
        response = {'message': str(e)}
        return jsonify(response), 400


@app.route('/chain', methods=['GET'])
def full_chain():
    chain = blockchain.chain
    response = {
        'chain': [block.__dict__ for block in chain],
        'length': len(chain),
    }
    return jsonify(response), 200


@app.route('/nodes/register', methods=['POST'])
def register_nodes():
    values = request.get_json()
    nodes = values.get('nodes')

    if nodes is None:
        return jsonify({'message': 'Invalid node list'}), 400

    for node in nodes:
        blockchain.register_node(node)

    response = {
        'message': 'Nodes have been added',
        'total_nodes': list(blockchain.nodes),
    }
    return jsonify(response), 201


@app.route('/nodes/resolve', methods=['GET'])
def consensus():
    replaced = blockchain.resolve_conflicts()

    if replaced:
        response = {
            'message': 'Our chain was replaced',
            'new_chain': [block.__dict__ for block in blockchain.chain]
        }
    else:
        response = {
            'message': 'Our chain is authoritative',
            'chain': [block.__dict__ for block in blockchain.chain]
        }

    return jsonify(response), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
