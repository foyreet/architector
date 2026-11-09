FROM python:3.11-slim
RUN pip install --no-cache-dir numpy==2.2.6 pandas==2.2.3 scikit-learn==1.7.2
COPY runner.py /runner.py
USER 10001:10001
WORKDIR /tmp
ENV OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
ENTRYPOINT ["python", "-I", "/runner.py"]

