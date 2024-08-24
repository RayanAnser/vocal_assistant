#!/usr/bin/env python3

import argparse
import queue
import sys
import sounddevice as sd
import os
from dotenv import load_dotenv
import openai
from vosk import Model, KaldiRecognizer
from boto3 import Session
from botocore.exceptions import BotoCoreError, ClientError
from contextlib import closing
import os
import sys
import subprocess
from playsound import playsound
from tempfile import gettempdir

q = queue.Queue()

def int_or_str(text):
    """Helper function for argument parsing."""
    try:
        return int(text)
    except ValueError:
        return text

def callback(indata, frames, time, status):
    """This is called (from a separate thread) for each audio block."""
    if status:
        print(status, file=sys.stderr)
    q.put(bytes(indata))

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument(
    "-l", "--list-devices", action="store_true",
    help="show list of audio devices and exit")
args, remaining = parser.parse_known_args()
if args.list_devices:
    print(sd.query_devices())
    parser.exit(0)
parser = argparse.ArgumentParser(
    description=__doc__,
    formatter_class=argparse.RawDescriptionHelpFormatter,
    parents=[parser])
parser.add_argument(
    "-f", "--filename", type=str, metavar="FILENAME",
    help="audio file to store recording to")
parser.add_argument(
    "-d", "--device", type=int_or_str,
    help="input device (numeric ID or substring)")
parser.add_argument(
    "-r", "--samplerate", type=int, help="sampling rate")
parser.add_argument(
    "-m", "--model", type=str, help="language model; e.g. en-us, fr, nl; default is en-us")
args = parser.parse_args(remaining)

try:
    if args.samplerate is None:
        device_info = sd.query_devices(args.device, "input")
        # soundfile expects an int, sounddevice provides a float:
        args.samplerate = int(device_info["default_samplerate"])

    if args.model is None:
        model = Model(lang="en-us")
    else:
        model = Model(lang=args.model)

    if args.filename:
        dump_fn = open(args.filename, "wb")
    else:
        dump_fn = None

    recognized_text = "" # Variable pour stocker le texte reconnu

    with sd.RawInputStream(samplerate=args.samplerate, blocksize = 8000, device=args.device,
            dtype="int16", channels=1, callback=callback):
        print("#" * 80)
        print("Press Ctrl+C to stop the recording")
        print("#" * 80)

        rec = KaldiRecognizer(model, args.samplerate)
        while True:
            data = q.get()
            if rec.AcceptWaveform(data):
                result = rec.Result()
                recognized_text = result.strip('"{}').strip()
                response = ""
                print(recognized_text)
                # print(f"Le texte reconnu est :{recognized_text}") # Afficher la phrase complète
                if recognized_text !='"text" : ""':
                    recognized_text = recognized_text.replace('"text" : "', "")
                    print(f"le second texte est {recognized_text}")
                    # Connexion open_ai
                    load_dotenv()
                    api_key = os.getenv('OPEN_AI_KEY')

                    # Configurer l'API OpenAI
                    openai.api_key = api_key

                    # Préparer les messages pour la conversation
                    messages = [
                        {"role": "user", "content": recognized_text}
                    ]
                    # Effectuer la requête de chat
                    response = openai.ChatCompletion.create(
                        model="gpt-4o-mini",  # Nom du modèle
                        messages=messages,      # Messages de la conversation
                        temperature=0.7        # Paramètre de température (ajustez si nécessaire)
                    )

                    # Afficher la réponse
                    print(response.choices[0].message.content)
                    recognized_text = ""
                print(response)
                if response != "":
                    session = Session(profile_name="adminuser")
                    polly = session.client("polly")
                    try:
                        # Request speech synthesis
                        response = polly.synthesize_speech(Text=response.choices[0].message.content, OutputFormat="mp3",
                                                            VoiceId="Joanna")
                    except (BotoCoreError, ClientError) as error:
                        # The service returned an error, exit gracefully
                        print(error)
                        sys.exit(-1)
                    # Access the audio stream from the response
                    if "AudioStream" in response:
                        # Note: Closing the stream is important because the service throttles on the
                        # number of parallel connections. Here we are using contextlib.closing to
                        # ensure the close method of the stream object will be called automatically
                        # at the end of the with statement's scope.
                            with closing(response["AudioStream"]) as stream:
                                output = os.path.join(gettempdir(), "speech.wav")

                                try:
                                # Open a file for writing the output as a binary stream
                                    with open(output, "wb") as file:
                                        file.write(stream.read())
                                except IOError as error:
                                    # Could not write to file, exit gracefully
                                    print(error)
                                    sys.exit(-1)
                                subprocess.call(["mpg123", output]) 
                                sd.default.device = None #désactive micro pour stream

                    else:
                        # The response didn't contain audio data, exit gracefully
                        print("Could not stream audio")
                        sys.exit(-1)


                    # Play the audio using the platform's default player
                    # if sys.platform == "win32":
                    #     os.startfile(output)
                    # else:
                    #     # The following works on macOS and Linux. (Darwin = mac, xdg-open = linux).
                    #     opener = "open" if sys.platform == "darwin" else "xdg-open"
                    #     subprocess.call([opener, output])
            else:
                # recognized_text += rec.PartialResult() # Accumuler les résultats partiels
                print(f"En cours de reconnaissance : {recognized_text}") # Afficher les résultats partiels
            if dump_fn is not None:
                dump_fn.write(data)

except KeyboardInterrupt:
    print("\nDone")
    parser.exit(0)
except Exception as e:
    parser.exit(type(e).__name__ + ": " + str(e))
