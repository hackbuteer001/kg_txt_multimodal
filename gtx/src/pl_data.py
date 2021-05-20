# Base pkgs
import os
import itertools
import pytorch_lightning as pl
from torch.utils.data.dataloader import DataLoader
from typing import Any, Callable, Dict, List, NewType, Optional, Tuple, Union

# User defined pkgs
from utils.dataset import get_dataset
from utils.data_collator import NodeClassification_DataCollator, NegativeSampling_DataCollator, UniLM_DataCollator, AdmLvlPred_DataCollator, ErrorDetection_DataCollator, Evaluation_DataCollator

# Huggingface Transformers Module
from transformers import (
    AutoTokenizer,
)
# Logging tool
from utils.notifier import logging, log_formatter
notifier = logging.getLogger(__name__)
notifier.addHandler(log_formatter())

class DataModule(pl.LightningDataModule):
    def __init__(self, data_args, model_args, training_args, config):
        super().__init__()
        self.data_args = data_args
        self.model_args = model_args
        self.args = training_args
        self.config = config

        # Load Tokenizer
        os.environ['TOKENIZERS_PARALLELISM'] = 'false'
        if model_args.tokenizer_name:
            tokenizer = AutoTokenizer.from_pretrained(self.model_args.tokenizer_name)
        elif model_args.model_name_or_path:
            tokenizer = AutoTokenizer.from_pretrained(self.model_args.model_name_or_path)
        else:
            raise ValueError(
                "You are instantiating a new tokenizer from scratch. This is not supported, but you can do it from another script, save it,"
                "and load it from here, using --tokenizer_name"
            )
        self.tokenizer = tokenizer

        # Set block size for padding & truncating inputs
        if data_args.block_size <= 0:
            data_args.block_size = tokenizer.model_max_length
        else:
            data_args.block_size = min(data_args.block_size, tokenizer.model_max_length)

    def prepare_data(self):
        self.train_dataset = get_dataset(
            self.data_args,
            tokenizer=self.tokenizer,
            token_type_vocab=self.config.token_type_vocab,
        )
        notifier.warning(self.train_dataset[0])
        self.eval_dataset = get_dataset(
            self.data_args,
            tokenizer=self.tokenizer,
            token_type_vocab = self.config.token_type_vocab,
            evaluate=True
        )
        self.test_dataset = get_dataset(
            self.data_args, 
            tokenizer=self.tokenizer, 
            token_type_vocab = self.config.token_type_vocab,
            test=True
        ) if self.args.do_eval else None

    def setup(self, stage): 
        COLLATORS = {
            "Pre": NodeClassification_DataCollator,
            "Re":NegativeSampling_DataCollator,
            "Gen":UniLM_DataCollator,
            "AdmPred":AdmLvlPred_DataCollator,
            "ErrDetect":ErrorDetection_DataCollator,
        }

        collator_args = {
            "tokenizer": self.tokenizer,
            "align": self.args.align,
            "n_negatives": self.args.n_negatives if stage=="fit" else 1,
            "edge_cls": self.args.edge_cls,
            "kg_special_token_ids": self.config.kg_special_token_ids,
            "kg_size": self.config.vocab_size['kg'],
            "num_kg_labels": self.config.num_kg_labels,
            "label_domain": self.args.label_domain
        }
        self.data_collator = COLLATORS[self.args.task](**{k:v for k,v in collator_args.items() if k in COLLATORS[self.args.task].__annotations__}, prediction=self.args.do_predict)

    def train_dataloader(self):
        return DataLoader(
            self.train_dataset,
            batch_size=self.args.train_batch_size,
            collate_fn=self.data_collator,
            drop_last=self.args.dataloader_drop_last,
            num_workers=self.args.dataloader_num_workers,
            pin_memory=self.args.dataloader_pin_memory,
            shuffle=True,
        )

    def val_dataloader(self):
        return DataLoader(
            self.eval_dataset,
            batch_size=self.args.eval_batch_size,
            collate_fn=self.data_collator,
            drop_last=False,
            num_workers=self.args.dataloader_num_workers,
            pin_memory=self.args.dataloader_pin_memory,
            shuffle=False)

    def test_dataloader(self, batch_size=None):
        return DataLoader(
            self.test_dataset,
            batch_size=self.args.eval_batch_size if batch_size is None else batch_size,
            collate_fn=self.data_collator,
            drop_last=False,
            num_workers=self.args.dataloader_num_workers,
            pin_memory=self.args.dataloader_pin_memory,
            shuffle=False)