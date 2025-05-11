FROM python
COPY . /qbit-hardlinker
WORKDIR /qbit-hardlinker
RUN pip install -r requirements.txt
CMD ["python", "hardlinker.py"]