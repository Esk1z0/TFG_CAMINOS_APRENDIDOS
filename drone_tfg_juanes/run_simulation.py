import os
import argparse

import gymnasium
import numpy as np
import torch
from stable_baselines3.common.env_util import SubprocVecEnv
from stable_baselines3.common.vec_env import VecMonitor

from environments_package.wrappers.remove_key_observation_wrapper import RemoveKeyObservationWrapper
from environments_package.wrappers.scale_action_wrapper import ScaleActionWrapper
from environments_package.wrappers.fixed_head_neck_action_wrapper import FixHeadNeckActionWrapper
from configs.trainning_config_loader import TrainingConfigLoader
from models_package.algorithm_factory import RLModelFactory


def parse_args():
    """Parsea los argumentos de línea de comandos para determinar la ruta base de guardado y el modo de ejecución."""
    parser = argparse.ArgumentParser(description="Entrenamiento o evaluación con SB3 y Webots.")
    parser.add_argument(
        "--save-dir",
        type=str,
        default=".",
        help="Directorio para guardar modelos y logs."
    )
    parser.add_argument(
        "--mode",
        choices=["train", "eval"],
        default="eval",
        help="Modo de ejecución: 'train' para entrenar, 'eval' para evaluar el modelo."
    )
    return parser.parse_args()



def make_env(world_path, reward_json_path, no_render):
    """Devuelve una función de inicialización del entorno, con todos los wrappers aplicados."""
    def _init():
        env = gymnasium.make(
            'tfg_juanes/CustomBioloid-v1',
            simulation_path=world_path,
            reward_json_path=reward_json_path,
            no_render=no_render
        )
        # Aplicamos los wrappers necesarios al entorno
        env = RemoveKeyObservationWrapper(env, remove_keys=["compass", "neck_1_sensor", "neck_2_sensor", "pelvis_sensor", "gps"])
        env = ScaleActionWrapper(env)
        env = FixHeadNeckActionWrapper(env, fixed_values={12: 0.0, 13: -1, 14: 0.0, 15: 0.0})
        return env
    return _init


def create_env(config, save_dir):
    """Crea un entorno vectorizado VecMonitor con múltiples entornos en paralelo."""
    env = SubprocVecEnv([
        make_env(
            config.env_config.get("world_path"),
            os.path.join(save_dir, config.env_config.get("reward_json_path")),
            config.env_config.get("no_render", False)
        ) for _ in range(config.train_config.get("num_envs", 1))
    ], start_method='spawn')
    env = VecMonitor(env)
    return env


def train_model(model, callbacks, model_factory, config):
    """Ejecuta el entrenamiento del modelo si aún quedan timesteps disponibles."""
    remaining_steps = config.train_config.get("timesteps") - model_factory.get_trained_steps()
    if remaining_steps > 0:
        print(f"[INFO] Timesteps por entrenar: {remaining_steps}")
        model.learn(
            total_timesteps=remaining_steps,
            reset_num_timesteps=False,
            callback=callbacks,
            log_interval=1
        )
    print("[INFO] Entrenamiento finalizado.")


def evaluate_model(model, env):
    """Ejecuta una evaluación del modelo entrenado y muestra la recompensa total."""
    obs = env.reset()
    done = False
    total_reward = 0

    while not done:
        action, _ = model.predict(obs)#, deterministic=True)
        obs, reward, terminated, truncated = env.step(action)

        done = any(terminated) or any(t.get("TimeLimit.truncated", False) for t in truncated)
        total_reward += reward[0] if isinstance(reward, (list, np.ndarray)) else reward

    env.close()
    print(f"[INFO] Evaluación finalizada. Recompensa total: {total_reward}")


def main():
    print(f"[INFO] Dispositivo: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'}")

    args = parse_args()
    save_dir = args.save_dir
    mode = args.mode

    config = TrainingConfigLoader(os.path.join(save_dir, "config.json")).load()
    env = create_env(config, save_dir)
    model_factory = RLModelFactory(config, env, save_dir)
    model, callbacks = model_factory.create_or_load_model()

    if mode == "train":
        train_model(model, callbacks, model_factory, config)
    elif mode == "eval":
        evaluate_model(model, env)


if __name__ == "__main__":
    main()
