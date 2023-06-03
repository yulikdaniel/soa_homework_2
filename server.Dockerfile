FROM python:3.11
RUN pip install grpcio-tools
RUN pip install requests
COPY protos protos
RUN python -m grpc_tools.protoc -I=protos --python_out=protos --grpc_python_out=protos protos/messages.proto protos/server.proto protos/client.proto
COPY src src
CMD ["python3", "src/server.py"]