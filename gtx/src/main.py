# Base pkgs
import os
import json
import pytorch_lightning as pl
# Usr defined pckgs
from pl_data import DataModule
from pl_model import GTXModel
from utils.parameters import parser
# Logging tool
from utils.notifier import logging, log_formatter
notifier = logging.getLogger(__name__)
notifier.addHandler(log_formatter())

# def get_deepspeed_config(path):
#     if path:
#         ds_config = pl.plugins.DeepSpeedPlugin(config=path)
#         return ds_config
#     else:
#         return None

def get_trainer_config(args):
    # We will collect callbacks!
    callbacks = list()

    # - LR monitoring Criteria
    lr_monitor_callback = pl.callbacks.LearningRateMonitor(
        logging_interval="step"
    )
    
    # - Early stop Criteria
    monitoring_target = {
        "Pre":None,
        "Re":"valid_acc",
        "AdmPred":"valid_loss",
        "ErrDetect":"valid_loss",
        "Gen":"valid_lm_acc",
        "ReAdm":"valid_AUROC",
        "NextDx":"valid_macro_AUROC",
        'Death30':"valid_AUROC",
        'Death180': "valid_AUROC",
        'Death365': "valid_AUROC",
    }
    
    if args.task != "Pre":
        if args.task != "Gen":
            early_stop_callback = pl.callbacks.EarlyStopping(
                monitor=monitoring_target[args.task],
                patience=2,
                mode="min" if args.task in ['AdmPred', 'ErrDetect'] else "max",
            )
            callbacks.append(early_stop_callback)
        else:  # Generation Task
            early_stop_callback = pl.callbacks.EarlyStopping(
                monitor=monitoring_target[args.task],
                min_delta=0.001 if args.task != "Gen" else 0.005,
                patience=3,
                verbose=True,
                mode="max",
            )
            # callbacks.append(early_stop_callback)
            callbacks.append(lr_monitor_callback)

    if args.use_tpu:
        tpu_core_id = 8
    else:
        tpu_core_id = None

    config = { 
        "max_epochs":args.num_train_epochs,
        "precision":16 if args.fp16 else 32,
        "gpus":None if args.use_tpu else -1,
        "tpu_cores":tpu_core_id,
        "accelerator": None,
        "log_every_n_steps":None if args.use_tpu else 50,
        "callbacks":callbacks,
        # "check_val_every_n_epoch":50,
        "val_check_interval":1.0 if args.task in ["Pre"] else 0.5,
    }
    if not args.do_eval:
        config["val_check_interval"]=1e10
        
    if args.task == "Gen":
        config["val_check_interval"]=1.0
        config["check_val_every_n_epoch"]=5

    return config

def main():
    # Parse arguments
    model_args, data_args, training_args = parser.parse_args_into_dataclasses()
    data_args.knowmix = training_args.knowmix
    data_args.task = training_args.task

    # Set seed
    pl.seed_everything(training_args.seed)

    # Call Logger
    wandb_config = dict()
    wandb_config.update(vars(training_args))
    wandb_config.update(vars(model_args))
    logger = pl.loggers.WandbLogger(config=wandb_config, project='MedGTX', group=training_args.run_name, name=f"{training_args.run_name},RNG{training_args.seed}", log_model=False, save_dir='logs')

    # Call Model
    gtx = GTXModel(model_args, training_args)
    if training_args.unimodal:
        data_args.gcn = True
    else:
        data_args.gcn = gtx.model.config.gcn

    # Call data module  
    data_module = DataModule(data_args, model_args, training_args, config=gtx.model.config)
    
    # Call Trainer
    trainer = pl.Trainer(
        **get_trainer_config(training_args),
        num_sanity_val_steps=4,
        logger=logger,
        # profiler='advanced',
        # fast_dev_run=10,
        # plugins=get_deepspeed_config(training_args.deepspeed),
    ) 
        
    # Train & Validation
    if training_args.do_train:
        # trainer.validate(model=gtx, datamodule = data_module)
        trainer.fit(gtx, data_module)
        if training_args.task == "Pre":
            gtx.save()
            data_module.save()
        else:
            gtx.save()
            notifier.critical("Trained model is successfully saved!")
        
    # Test
    if training_args.do_eval:
        if not training_args.do_train:
            data_module.prepare_data()
            data_module.setup('test')
        trainer.test(model=gtx, datamodule=data_module)

if __name__ == "__main__":
    main()