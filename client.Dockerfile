FROM python:3.11
RUN pip install grpcio-tools
COPY protos protos
RUN python -m grpc_tools.protoc -I=protos --python_out=protos --grpc_python_out=protos protos/messages.proto protos/server.proto protos/client.proto
COPY src/client.py src/client.py
CMD ["python3", "src/client.py"]