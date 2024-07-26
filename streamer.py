import os
import io
import sys
import time
import shutil
import json
import chess
import chess.engine
import chess.pgn
import threading
import subprocess
import traceback
from random import sample, randint
from PIL import Image, ImageDraw, ImageFont

print("loading ...\r", end='')
framerate = 30
resolution = (1920, 1080)
x_table = {c:n for n,c in enumerate('abcdefgh')}
board_temp = [["bR","bN","bB","bQ","bK","bB","bN","bR"],
             ["bP" for _ in range(8)                  ],
             [".." for _ in range(8)                  ],
             [".." for _ in range(8)                  ],
             [".." for _ in range(8)                  ],
             [".." for _ in range(8)                  ],
             ["wP" for _ in range(8)                  ],
             ["wR","wN","wB","wQ","wK","wB","wN","wR"]]
piece_img = {code:Image.open(f"img/chesspieces/{code}.png") for code in ['wP','wN','wB','wR','wQ','wK','bP','bN','bB','bR','bQ','bK']}
keyword = ['depth', 'seldepth', 'pv', 'cp', 'nps']
stdread = ''
iswhite = None
total_time = None

class Timer:
  def __init__(self):
    self.time = millis()
  def check(self, target):
    return self.elapsed() > target
  def elapsed(self):
    return millis() - self.time
  def reset(self):
    self.time = millis()
    
# ffmpeg_command = [
#   'ffmpeg',
#   '-i', '-',
#   '-re', '-f', 'lavfi',
#   '-i', 'anullsrc',
#   '-vf', 'scale=-2:480,format=yuv444p',
#   '-r', str(framerate),
#   '-g', str(framerate*3),
#   '-maxrate', '2048k',
#   '-bufsize', '2048k',
#   '-c:v', 'libx264',
#   '-c:a', 'aac',
#   '-preset', 'ultrafast',
#   '-f', 'flv',
#   'rtmp://a.rtmp.youtube.com/live2/gwv5-689m-6378-0t7g-4tgp'
#   # '-loglevel',  'quiet'
# ]
# ffmpeg_command = [
#   'ffmpeg',
#   '-i', '-',
#   '-vf', 'scale=-1:480',
#   '-f', 'mpegts',
#   'udp://192.168.43.1:6969',
#   '-loglevel',  'error'
# ]
ffmpeg_command = [
  'ffplay',
  '-i', '-',
  '-vf', 'scale=-1:480',
  '-loglevel', 'error'
]
ffmpeg = subprocess.Popen(ffmpeg_command, stdin=subprocess.PIPE)
# move_sound = io.BytesIO(open("sound/move-self.mp3","rb").read())
# TODO: add sound to move, but maybe need another process of ffmpeg

def updater(process):
  global stdread, movestack, result
  for line in iter(process.stdout.readline, ""):
    if 'bestmove' in line: movestack.append((line, millis()))
    if 'Finished game 1' in line:
      result = line
      break
    stdread = line

def call_engine(path):
  try: process = subprocess.Popen(path, stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, bufsize=1)
  except: return None
  def send_command(command):
    try:
      process.stdin.write(command + '\n')
      process.stdin.flush()
    except: pass
  def read_output():
    output = []
    process_time = Timer()
    while True:
      try: line = process.stdout.readline().strip()
      except: break
      if line == "uciok": break
      if process_time.elapsed() > 5000: break
      if process.poll() is not None: return None
      output.append(line)
    return output
  send_command("uci")
  output_lines = read_output()
  if output_lines is None: return None
  info = None
  for line in output_lines:
    if line.startswith("id name"):
      info = line.strip("id name ")
  send_command("quit")
  terminate(process)
  if info is None or info.split() == []: return (path.split('/')[-1], "unknown")
  split_info = info.split()
  if len(split_info) == 1: return (split_info[0], "unknown")
  name, version = split_info[:2]
  if version.lower() == "by": return (name, "unknown")
  return (name, version)

def is_checkmate(board):
  test_board = chess.Board()
  test_board.clear_board()
  for y in range(8):
    for x in range(8):
      test_board.set_piece_at(y*8+x, chess.Piece(board[y][x][1], True if board[y][x][0] == 'w' else False))
  return test_board.is_checkmate()

def millis():
  return time.time() * 1000

def millis_to_human(mil):
  ret = None
  ch, milsecond = divmod(mil, 1000)
  ch, second = divmod(ch, 60)
  ch, minute = divmod(ch, 60)
  ch, hour = divmod(ch, 24)
  ch, day = divmod(ch, 7)
  ch, week = divmod(ch, 4)
  month = ch
  if month > 0: ret = f"{int(month)} months"
  elif week > 0: ret = f"{int(week)} weeks"
  elif day > 0: ret = f"{int(day)} days"
  elif hour > 0: ret = f"{int(hour)} hours"
  elif minute > 0: ret = f"{int(minute)} minutes"
  elif second > 0: ret = f"{int(second)} seconds"
  else: return "now"
  if ret.split()[0] == '1': return ret[:-1]
  return ret
  
def millis_to_timestr(mil: int):
  if mil < 0:
    return "0:00"
  ch, milsecond = divmod(mil, 1000)
  ch, second = divmod(ch, 60)
  ch, minute = divmod(ch, 60)
  hour = ch
  time_str = ''
  if hour != 0:
    time_str += f"{int(hour):01}:"
    time_str += f"{int(minute):02}:"
  else:
    time_str += f"{int(minute):01}:"
  time_str += f"{int(second):02}"
  if hour == 0 and minute == 0 and second < 10: time_str += f".{int(milsecond/100)}"
  return time_str

def format_num(x):
  if x < 1000: return str(x)
  elif x < 1000_000: return f"{x//1000}K"
  else: return f"{x//1000_000}M"

def color_accent(base_color:tuple, accent:str):
  if accent == "light":        return tuple(min(220, value + 120) for value in base_color)
  elif accent == "superlight": return tuple(min(220, value + 210) for value in base_color)
  elif accent == "dark":       return tuple(round(0.4 * value) for value in base_color)
  elif accent == "pastel":     return tuple((value + 255) // 2 for value in base_color)
  return None

def move_curve(x):
  x = min(x, 1)
  # return x * x * (3.0 - 2.0 * x) # bezier
  return x*x / (2.0 * (x*x - x) + 1.0) # parametric
  
def get_info(string, keyword):
  info = {}
  iskeyword = False
  for word in string.split():
    if iskeyword:
      info[current_keyword] = word
      iskeyword = False
    else:
      if word in keyword:
        current_keyword = word
        iskeyword = True
  return info

def get_font(typ, size):
  typs = ["default", "light", "bold", "oblique", "bold_oblique"]
  if not typ in typs: raise Exception("bad font type")
  return ImageFont.truetype(f"fonts/Helvetica/helvetica_{typ}.ttf", size)

def get_table(header, body, numbered=False):
  assert len(header) == len(body) and len(header) > 0, f"header: {len(header)}  body:{len(body)}"
  table   = ''
  spacing = [0]
  margin  = 4
  for n, head in enumerate(header):
    lengths = (len(head),) + tuple(len(item) for item in body[n]) 
    spacing.append(max(lengths))
  if numbered:
    spacing[0] = len(str(len(body[0]))) + 2
    table += ' ' * spacing[0]
  for n, head in enumerate(header):
    table += head + ' ' * (spacing[n+1]-len(head) + margin)
  table += '\n'
  for n in range(len(body[0])):
    if numbered:
      table += f'{n+1}. ' + ' ' * (spacing[0]-len(f'{n+1}. '))
    for m in range(len(body)):
      table += body[m][n] + ' ' * (spacing[m+1] - len(body[m][n]) + margin)
    table += '\n'
  return table
  
def clamp(n, limit):
  return max(0, min(n, limit))

def update_elo(rating_a, rating_b, result, K=32):
  expected_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
  new_rating_a = rating_a + K * (result - expected_a)
  return new_rating_a

def send_frame(data):
  global ffmpeg
  try: ffmpeg.stdin.write(data)
  except:
    terminate(ffmpeg)
    ffmpeg = subprocess.Popen(ffmpeg_command, stdin=subprocess.PIPE)
    ffmpeg.stdin.write(data)
  
def match_handle(game_info, engine_info, engine1, engine2, tc):
  global ffmpeg, stdread, movestack, result, piece_img, total_time
  tc_split = tc[1:].split(':')
  engine1_name = engine_info[engine1]['name']
  engine2_name = engine_info[engine2]['name']
  time_control = (int(tc_split[0])*60 + int(tc_split[1])) * 1000
  if time_control > 100*60*60*1000:
    print("ERROR: time control surpassed limit of 100h")
    exit()
  standing = dict(sorted({i:engine_info[i]['score'] for i in engine_info}.items(), key=lambda item: item[1], reverse=True))
  main_color = game_info[2]
  bg_color = color_accent(main_color, "pastel")
  fill_color = color_accent(main_color , "superlight")
  # building frame
  frame = Image.new("RGB", resolution, bg_color)
  d = ImageDraw.Draw(frame)
  square_size = 90
  light_color = "beige"
  dark_color = main_color
  x_offset = resolution[0]//10 - 30
  y_offset = resolution[1]//2 - int(square_size*4)
  bar_offset = x_offset+square_size*8+20
  time_offset = (resolution[0]//3)+80
  for i in range(8):
    for j in range(8):
      if (i + j) % 2 == 0: color = light_color
      else: color = dark_color
      x_start = j*square_size + x_offset
      y_start = i*square_size + y_offset
      square_coords = [(x_start, y_start), (x_start+square_size, y_start+square_size)]
      d.rectangle(square_coords, fill=color)
      piece_code = board_temp[i][j]
      if piece_code != "..":
        piece = piece_img[piece_code]
        size = piece.size
        assert size[0] == size[1] # image is a perfect square
        new_size = (square_size, square_size)
        piece = piece.resize(new_size)
        frame.paste(piece, (x_start, y_start), piece)
  # time
  time_shade = Image.new("RGBA", (206, 56), (0, 0, 0, 150))
  d.rectangle((time_offset-5, 960-5, time_offset+200+1, 1010+1), fill=fill_color)
  d.rectangle((time_offset-5, 80-5, time_offset+200+1, 130+1), fill=fill_color)
  d.text((time_offset, 960), millis_to_timestr(time_control), font=get_font("bold", 48), fill="black")
  d.text((time_offset, 80), millis_to_timestr(time_control), font=get_font("bold", 48), fill="black")
  d.rectangle((time_offset-10, 75-5, time_offset+200+5, 130+5), width=4, outline=(20,)*3)
  d.rectangle((time_offset-10, 955-5, time_offset+200+5, 1010+5), width=4, outline=(20,)*3)
  # movelist
  d.rectangle((bar_offset+150-7, 250-7, bar_offset+200+240+7, 300+230+7), fill=fill_color)
  d.rectangle((bar_offset+150-10, 250-10, bar_offset+200+240+10, 300+230+10), width=3, outline=(20,)*3)
  # recent games
  d.rectangle((bar_offset+150-7, 580-7, bar_offset+200+240+7, 825+7), fill=fill_color)
  d.rectangle((bar_offset+150-10, 580-10, bar_offset+200+240+10, 825+10), width=3, outline=(20,)*3)
  d.text((bar_offset+165, 680), "Recent Games", font=get_font("bold", 36), fill="grey")
  # engine output
  d.rectangle((bar_offset+150-10, 860-2, resolution[0]-160+2, 890+2), width=2, outline=(20,)*3)
  d.rectangle((bar_offset+150-10, 180-2, resolution[0]-160+2, 210+2), width=2, outline=(20,)*3)
  d.rectangle((bar_offset+150-7, 860, resolution[0]-160, 890), fill=fill_color)
  d.rectangle((bar_offset+150-7, 180, resolution[0]-160, 210), fill=fill_color)
  d.text((1920 - (resolution[0]//2) + 100, 860+5), "Depth:", font=get_font("bold", 24), fill="black")
  d.text((1920 - (resolution[0]//2) + 280, 860+5), "Move:", font=get_font("bold", 24), fill="black")
  d.text((1920 - (resolution[0]//2) + 460, 860+5), "Score:", font=get_font("bold", 24), fill="black")
  d.text((1920 - (resolution[0]//2) + 620, 860+5), "NPS:", font=get_font("bold", 24), fill="black")
  d.text((1920 - (resolution[0]//2) + 100, 180+5), "Depth:", font=get_font("bold", 24), fill="black")
  d.text((1920 - (resolution[0]//2) + 280, 180+5), "Move:", font=get_font("bold", 24), fill="black")
  d.text((1920 - (resolution[0]//2) + 460, 180+5), "Score:", font=get_font("bold", 24), fill="black")
  d.text((1920 - (resolution[0]//2) + 620, 180+5), "NPS:", font=get_font("bold", 24), fill="black")
  # eval bar
  white_bar = Image.new("RGB", (20, square_size*4), (255, 255, 255))
  black_bar = Image.new("RGB", (20, square_size*4), (0, 0, 0))
  d.rectangle((bar_offset, y_offset, bar_offset+20-1, y_offset+square_size*8), fill="white")
  frame.paste(black_bar, (bar_offset, y_offset))
  frame.paste(white_bar, (bar_offset, y_offset+square_size*4))
  # standing table
  d.rectangle((bar_offset+500-7, 250-7, bar_offset+500+350+7, 300+525+7), fill=fill_color)
  d.rectangle((bar_offset+500-10, 250-10, bar_offset+500+350+10, 300+525+10), width=3, outline=(20,)*3)
  for n,i in list(enumerate(standing))[:14]:
    d.text((bar_offset+510, 265+40*n), str(n+1)+'.', font=get_font("default", 20), fill="grey")
    d.text((bar_offset+550, 265+40*n), (engine_info[i]['name']+' '+engine_info[i]['version'])[:24], font=get_font("default", 20), fill="black")
    if standing[i] == 0.5:     d.text((bar_offset+800, 265+40*n), '½', font=get_font("default", 20), fill="black")
    elif standing[i]%1 == 0.5: d.text((bar_offset+800, 265+40*n), str(int(standing[i]//1))+'½', font=get_font("default", 20), fill="black")
    else:                      d.text((bar_offset+800, 265+40*n), str(int(standing[i])), font=get_font("default", 20), fill="black")
  # engine name
  d.text((x_offset, 930), engine1_name+f" #{list(standing).index(engine1)+1}", font=get_font("bold", 42), fill="black")
  d.text((x_offset, 930+50), "Version: "+engine_info[engine1]['version'], font=get_font("default", 24), fill="black")
  d.text((x_offset, 930+85), f"W: {engine_info[engine1]['win']}   D: {engine_info[engine1]['draw']}   L: {engine_info[engine1]['lose']}", font=get_font("default",22), fill="black")
  d.text((x_offset, 60), engine2_name+f" #{list(standing).index(engine2)+1}", font=get_font("bold", 42), fill="black")
  d.text((x_offset, 60+50), "Version: "+engine_info[engine2]['version'], font=get_font("default", 24), fill="black")
  d.text((x_offset, 60+85), f"W: {engine_info[engine2]['win']}   D: {engine_info[engine2]['draw']}   L: {engine_info[engine2]['lose']}", font=get_font("default",22), fill="black")
  # game info and progress bar
  tc_split = tc[1:].split(":")
  if game_info[0] == 1: total_time = int(tc_split[0])*120*1000 + int(tc_split[1])*2*1000  # will break for larger time control
  progress_bar = Image.new("RGB", (600, 10), main_color)
  progress_indbar = Image.new("RGB", (int(game_info[0]/game_info[1]*600), 10), color_accent(main_color, "dark"))
  frame.paste(progress_bar, (bar_offset+200, 130))
  frame.paste(progress_indbar, (bar_offset+200, 130))
  d.text((bar_offset+200, 90), f"({tc_split[0]}+{tc_split[1]})  Game {game_info[0]} of {game_info[1]}", font=get_font("bold", 28), fill="black")
  estimated_font = get_font("oblique", 20)
  avg_game_time = total_time/game_info[0]
  estimated_time = "~about " + millis_to_human((game_info[1]-game_info[0]+1)*avg_game_time)
  d.text((bar_offset+200+600-int(estimated_font.getlength(estimated_time)), 100), estimated_time, font=estimated_font, fill="black")

  print(f"starting match {game_info[0]}/{game_info[1]}: {engine_info[engine1]['name']} -- {engine_info[engine2]['name']}")
  cutechess_command = [
    'cutechess/cutechess-cli.exe',
    '-engine', f'cmd={engine1}',
    '-engine', f'cmd={engine2}',
    '-each', f'tc={tc}', 'proto=uci',
    '-wait', '1',
    '-pgnout', 'result/games.pgn', 'min',
    '-debug'
  ]
  process = subprocess.Popen(cutechess_command, stdout=subprocess.PIPE, universal_newlines=True, bufsize=1)
  thread = threading.Thread(target=updater, args=(process,))
  thread.daemon = True
  thread.start()
  fps = framerate+0
  frame_sent = 0
  movestack = []
  movelist = []
  # board = board_temp  # not working
  # TODO: use python-chess library for board representaion
  board = [["bR","bN","bB","bQ","bK","bB","bN","bR"],
           ["bP" for _ in range(8)                  ],
           [".." for _ in range(8)                  ],
           [".." for _ in range(8)                  ],
           [".." for _ in range(8)                  ],
           [".." for _ in range(8)                  ],
           ["wP" for _ in range(8)                  ],
           ["wR","wN","wB","wQ","wK","wB","wN","wR"]]
  move_timed = millis()
  fps_time = Timer()
  frame_time = Timer()
  standing_time = Timer()
  game_time = Timer()
  white_time = time_control
  black_time = time_control
  white_score = 0
  black_score = 0
  standing_page = 0
  iswhite = True
  result = None
  
  while True:
    # TODO: maybe handle died process by displaying 'Game error. Match will restart.'?
    if process.poll() is not None and result is None: # check if cutechess is dead before game is finished
      print("Process died unexpectedly.")
      return None
      
    if fps_time.check(1000):
      fps = frame_sent+0
      print(f"FPS: {fps}\r", end='')
      # if framerate > frame_sent: print(f"WARNING: low FPS (target:{framerate}, real:{fps}), consider lowering framerate value")
      fps_time.reset()
      frame_sent = 0
    info = get_info(stdread, keyword)
      
    if movestack != []:
      move = get_info(movestack[0][0], ['bestmove'])['bestmove']
      if iswhite:
        white_time -= movestack[0][1]-move_timed
        movelist += [[len(movelist),(move,)]]
        frame.paste(time_shade, (time_offset-5, 960-5), time_shade) # draw shade on time
        d.rectangle((time_offset-5, 80-5, time_offset+200+1, 130+1), fill=fill_color)
        d.text((time_offset, 80), millis_to_timestr(black_time-(millis()-move_timed)), font=get_font("bold", 48), fill="black")
      else:
        black_time -= movestack[0][1]-move_timed
        movelist[-1][1] += (move,)
        frame.paste(time_shade, (time_offset-5, 80-5), time_shade) # draw shade on time
        d.rectangle((time_offset-5, 960-5, time_offset+200+1, 1010+1), fill=fill_color)
        d.text((time_offset, 960), millis_to_timestr(white_time-(millis()-move_timed)), font=get_font("bold", 48), fill="black")

      p = None
      if len(move) == 5: x1, y1, x2, y2, p = move
      else: x1, y1, x2, y2 = move
      x1 = x_table[x1]
      x2 = x_table[x2]
      y1 = abs(int(y1)-8)
      y2 = abs(int(y2)-8)
      piece = board[y1][x1]
      if p != None:
        if iswhite: piece = 'w' + p.upper()
        else: piece = 'b' + p.upper()

      board[y1][x1] = ".."

      if piece[1] == "P" and abs(x1-x2) == 1 and board[y2][x2] == "..":
        if iswhite: py = y2+1
        else: py = y2-1
        board[py][x2] = ".."
        img = Image.open(f"img/chesspieces/{'wP' if iswhite else 'bP'}.png")
        color = light_color if ((x2 + py) % 2 == 0) else dark_color
        x_start = x2*square_size + x_offset
        y_start = py*square_size + y_offset
        square_coords = [(x_start, y_start), (x_start+square_size, y_start+square_size)]
        d.rectangle(square_coords, fill=color)
        
      if piece[1] == "K" and abs(x1-x2) > 1:
        if x1 > x2: r = (0,3)
        else: r = (7,5)
        if iswhite: rook = "wR"
        else: rook = "bR"
        board[y1][r[0]] = ".."
        board[y2][r[1]] = rook
        color = light_color if ((r[0] + y1) % 2 == 0) else dark_color
        x_start = r[0]*square_size + x_offset
        y_start = y1*square_size + y_offset
        square_coords = [(x_start, y_start), (x_start+square_size, y_start+square_size)]
        d.rectangle(square_coords, fill=color)
        
        color = light_color if ((r[1] + y2) % 2 == 0) else dark_color
        x_start = r[1]*square_size + x_offset
        y_start = y2*square_size + y_offset
        square_coords = [(x_start, y_start), (x_start+square_size, y_start+square_size)]
        d.rectangle(square_coords, fill=color)
        img = Image.open(f"img/chesspieces/{rook}.png")
        size = img.size
        new_size = (square_size, square_size)
        img = img.resize(new_size)
        frame.paste(img, (x_start, y_start), img)

      # over-engineered move animation
      prev_x = None
      prev_y = None
      if len(movestack) <= 2 and fps > 10:
        animation_time = 200
        move_timer = Timer()
        while not move_timer.check(animation_time):
          val = move_curve((millis()-move_timer.time)/animation_time)
          x = int(square_size*x1 + square_size*val*(x2-x1))
          y = int(square_size*y1 + square_size*val*(y2-y1))
          if frame_time.check(1000/framerate):
            if prev_x != None:
              for xs,ys in ((((i)//square_size),((j)//square_size)) for j in [prev_y,prev_y+square_size] for i in [prev_x,prev_x+square_size]):
                if (0 <= xs <= 7) and (0 <= ys <= 7):
                  color = light_color if ((xs + ys) % 2 == 0) else dark_color
                  square_coords = [(xs*square_size+x_offset, ys*square_size+y_offset), (xs*square_size+x_offset+square_size, ys*square_size+y_offset+square_size)]
                  d.rectangle(square_coords, fill=color)
                  try: piece_code = board[ys][xs]
                  except: piece_code = ".."
                  if piece_code != "..":
                    pieceimg = piece_img[piece_code]
                    size = pieceimg.size
                    assert size[0] == size[1] # image is a perfect square
                    new_size = (square_size, square_size)
                    pieceimg = pieceimg.resize(new_size)
                    frame.paste(pieceimg, (xs*square_size+x_offset, ys*square_size+y_offset), pieceimg)
            if piece != "..":
              img = piece_img[piece]
              size = img.size
              new_size = (square_size, square_size)
              img = img.resize(new_size)
              frame.paste(img, (x+x_offset, y+y_offset), img)
              prev_x = x
              prev_y = y
            elif result is None: # got null move before game ends
              print(movelist, move)
              terminate(process)
              return None
            data = io.BytesIO()
            frame.save(data, format='JPEG')
            send_frame(data.getvalue())
            frame_time.reset()

      # draw piece on its final place after animation
      board[y2][x2] = piece
      color = light_color if ((x1 + y1) % 2 == 0) else dark_color
      x_start = x1*square_size + x_offset
      y_start = y1*square_size + y_offset
      square_coords = [(x_start, y_start), (x_start+square_size, y_start+square_size)]
      d.rectangle(square_coords, fill=color)
      if prev_x != None:
        for xs,ys in ((((i)//square_size),((j)//square_size)) for j in [prev_y,prev_y+square_size] for i in [prev_x,prev_x+square_size]):
          if (0 <= xs <= 7) and (0 <= ys <= 7):
            color = light_color if ((xs + ys) % 2 == 0) else dark_color
            square_coords = [(xs*square_size+x_offset, ys*square_size+y_offset), (xs*square_size+x_offset+square_size, ys*square_size+y_offset+square_size)]
            d.rectangle(square_coords, fill=color)
            try: piece_code = board[ys][xs]
            except: piece_code = ".."
            if piece_code != "..":
              pieceimg = piece_img[piece_code]
              size = pieceimg.size
              assert size[0] == size[1] # image is a perfect square
              new_size = (square_size, square_size)
              pieceimg = pieceimg.resize(new_size)
              frame.paste(pieceimg, (xs*square_size+x_offset, ys*square_size+y_offset), pieceimg)
      color = light_color if ((x2 + y2) % 2 == 0) else dark_color
      x_start = x2*square_size + x_offset
      y_start = y2*square_size + y_offset
      square_coords = [(x_start, y_start), (x_start+square_size, y_start+square_size)]
      d.rectangle(square_coords, fill=color)
      if piece != "..":
        img = piece_img[piece]
        size = img.size
        new_size = (square_size, square_size)
        img = img.resize(new_size)
        frame.paste(img, (x_start, y_start), img)
      elif result is None: # got null move before game ends
        print(movelist, move)
        terminate(process)
        return None

      height_white = clamp(square_size*4+int((white_score/50)*360), square_size*8)
      height_black = clamp(square_size*4+int((black_score/50)*360), square_size*8)
      d.rectangle((bar_offset, y_offset, bar_offset+20-1, y_offset+square_size*8), fill="white")
      white_bar = Image.new("RGBA", (20, height_white), (255, 255, 255, 127))
      black_bar = Image.new("RGB", (20, height_black), (0, 0, 0))
      frame.paste(black_bar, (bar_offset, y_offset))
      frame.paste(white_bar, (bar_offset, y_offset+square_size*8-white_bar.size[1]), white_bar)

      d.rectangle((bar_offset+150-7, 250-7, bar_offset+150+240+7, 300+230+7), fill=fill_color)
      for n,i in enumerate(movelist[-7:]):
        d.text((bar_offset+165, 260+n*40), f"{i[0]+1}.", font=get_font("default", 22), fill="grey")
        d.text((bar_offset+230, 260+n*40), f"{i[1][0]}", font=get_font("default", 22), fill="black")
        if len(i[1]) == 2: 
          d.text((bar_offset+330, 260+n*40), f"{i[1][1]}", font=get_font("default", 22), fill="black")
      move_timed = movestack[0][1]
      movestack.pop(0)
      iswhite = not iswhite

    if standing_time.check((3 + len(list(standing.keys())[14*standing_page:14*standing_page+14]))*1000):
      standing_page = (standing_page + 1) % -(len(engine_info.keys())//-14)
      d.rectangle((bar_offset+500-7, 250-7, bar_offset+500+350+7, 300+525+7), fill=fill_color)
      d.rectangle((bar_offset+500-10, 250-10, bar_offset+500+350+10, 300+525+10), width=3, outline=(20,)*3)
      for n,i in list(enumerate(standing))[14*standing_page:14*standing_page+14]:
        n -= 14*standing_page
        d.text((bar_offset+510, 265+40*n), str(n+14*standing_page+1)+'.', font=get_font("default", 20), fill="grey")
        d.text((bar_offset+550, 265+40*n), (engine_info[i]['name']+' '+engine_info[i]['version'])[:24], font=get_font("default", 20), fill="black")
        if standing[i] == 0.5:     d.text((bar_offset+800, 265+40*n), '½', font=get_font("default", 20), fill="black")
        elif standing[i]%1 == 0.5: d.text((bar_offset+800, 265+40*n), str(int(standing[i]//1))+'½', font=get_font("default", 20), fill="black")
        else:                      d.text((bar_offset+800, 265+40*n), str(int(standing[i])), font=get_font("default", 20), fill="black")
      standing_time.reset()

    if 'cp' in info:
      if iswhite: white_score = int(info['cp'])/10
      else: black_score = int(info['cp'])/10
      
    if iswhite:
      d.rectangle((time_offset-5, 960-5, time_offset+200+1, 1010+1), fill=fill_color)
      d.text((time_offset, 960), millis_to_timestr(white_time-(millis()-move_timed)), font=get_font("bold", 48), fill="black")
    else:
      d.rectangle((time_offset-5, 80-5, time_offset+200+1, 130+1), fill=fill_color)
      d.text((time_offset, 80), millis_to_timestr(black_time-(millis()-move_timed)), font=get_font("bold", 48), fill="black")

    # display local time
    d.rectangle((10,10,250,40), fill=bg_color)
    d.text((10,10), str(time.ctime()), font=get_font("default", 20), fill="black")

    # update engine thinking status
    if info != {}:
      depth_str = '-'
      move_str = f"{info['pv']}" if 'pv' in info else '-'
      score_str = f"{info['cp']}" if 'cp' in info else '-'
      nps_str = format_num(int(info['nps'])) if 'nps' in info else '-'
      if 'depth' in info: depth_str = f"{info['depth']}"
      if 'seldepth' in info: depth_str += f"/{info['seldepth']}"
      if iswhite:
        d.rectangle((1920 - (resolution[0]//2) + 180, 860, 1920 - (resolution[0]//2) + 280, 890), fill=fill_color)
        d.text((1920 - (resolution[0]//2) + 180, 860+5), depth_str, font=get_font("oblique", 24), fill="black")
        d.rectangle((1920 - (resolution[0]//2) + 360, 860, 1920 - (resolution[0]//2) + 460, 890), fill=fill_color)
        d.text((1920 - (resolution[0]//2) + 360, 860+5), move_str, font=get_font("oblique", 24), fill="black")
        d.rectangle((1920 - (resolution[0]//2) + 540, 860, 1920 - (resolution[0]//2) + 610, 890), fill=fill_color)
        d.text((1920 - (resolution[0]//2) + 540, 860+5), score_str, font=get_font("oblique", 24), fill="black")
        d.rectangle((1920 - (resolution[0]//2) + 690, 860, 1920 - (resolution[0]//2) + 800, 890), fill=fill_color)
        d.text((1920 - (resolution[0]//2) + 690, 860+5), nps_str, font=get_font("oblique", 24), fill="black")
      else:
        d.rectangle((1920 - (resolution[0]//2) + 180, 180, 1920 - (resolution[0]//2) + 280, 210), fill=fill_color)
        d.text((1920 - (resolution[0]//2) + 180, 180+5), depth_str, font=get_font("oblique", 24), fill="black")
        d.rectangle((1920 - (resolution[0]//2) + 360, 180, 1920 - (resolution[0]//2) + 460, 210), fill=fill_color)
        d.text((1920 - (resolution[0]//2) + 360, 180+5), move_str, font=get_font("oblique", 24), fill="black")
        d.rectangle((1920 - (resolution[0]//2) + 540, 180, 1920 - (resolution[0]//2) + 610, 210), fill=fill_color)
        d.text((1920 - (resolution[0]//2) + 540, 180+5), score_str, font=get_font("oblique", 24), fill="black")
        d.rectangle((1920 - (resolution[0]//2) + 690, 180, 1920 - (resolution[0]//2) + 800, 210), fill=fill_color)
        d.text((1920 - (resolution[0]//2) + 690, 180+5), nps_str, font=get_font("oblique", 24), fill="black")

    data = io.BytesIO()
    frame.save(data, format='JPEG')
    if frame_time.check(1000/framerate):
      send_frame(data.getvalue())
      # ffmpeg.stdin.write(move_sound.getvalue())
      frame_time.reset()
      frame_sent += 1
  
    if result != None and movestack == []:
      process.kill()
      thread.join()
      msg = None
      total_time += game_time.elapsed() + 10000
      if '0-1' in result:
        msg_big = "Black won"
        point = (0,1)
      elif '1-0' in result:
        msg_big = "White won"
        point = (1,0)
      elif '1/2-1/2' in result:
        msg_big = "Draw"
        point = (0.5,0.5)
      if 'mates' in result: msg = "Checkmate."
      elif 'loses on time' in result: msg = "Timeout."
      elif '3-fold' in result: msg = "Repetition."
      elif 'insufficient' in result: msg = "Insufficient material."
      elif 'stalemate' in result: msg = "Stalemate."
      elif 'timeout' in result: msg = "Timeout and insufficient material."
      elif 'fifty moves' in result: msg = "Fifty moves."
      elif 'illegal move' in result: msg = "Illegal move."
      elif 'disconnects' in result: msg = "Disconnected."
      elif 'stalls' in result: msg = "Stalled."
      if msg == None: msg = "Null."; print(f"WARNING: unhandled message ('{msg}')")
      shade = Image.new("RGBA", (8*square_size+1, 8*square_size+1), (0, 0, 0, 150))
      frame.paste(shade, (x_offset, y_offset), shade)
      big_font = get_font("bold", 56)
      font = get_font("default", 32)
      d.text((x_offset+square_size*4-big_font.getlength(msg_big)//2, y_offset+square_size*4-60), msg_big, font=big_font, fill="white")
      d.text((x_offset+square_size*4-font.getlength(msg)//2, y_offset+square_size*4+15), msg, font=font, fill=(210,210,210))
      data = io.BytesIO()
      frame.save(data, format='JPEG')
      result_show = Timer()
      while not result_show.check(10*1000):
        send_frame(data.getvalue())
        time.sleep(1/framerate)
      print(point, msg)
      return point

def terminate(p):
  try: p.kill()
  except Exception as e: print(e)

# TODO: update engine's presence even if folder exist in config.json
def find_engine(folder):
  # folder exception
  for i in ['.git','tmp','cache','script','CMakeFiles','.fingerprint','deps','target/release/build']:
    if i in folder: return
  folder_list = os.listdir(folder)
  engine_list = []
  for item in folder_list:
    item = folder + '/' + item
    if os.path.isdir(item):
      yield from find_engine(item)
    if os.path.isfile(item) and shutil.which(item):
      if item.split('.')[-1] not in ['c','h','so','sh','hh','py','out','bin','dll']:
        yield item
      
def main():
  global main_color
  # load from configuration file
  engine_info = {}
  f_list = os.listdir('engines')
  if os.path.exists("config.json"):
    config = json.load(open("config.json"))
  else: config = []
  for f in f_list:
    f = 'engines/' + f
    if os.path.isfile(f) and shutil.which(f):
      if sum(i['engine'] == f for i in config) == 0:
        config.append({'dir':None,'engine':f})
    if os.path.isdir(f):
      if sum(i['dir'] == f for i in config) == 0:
        engines = list(find_engine(f))
        info = {
          'dir':f,
          'build_dir':None,
          'engine':None,
          'build_command':None
        }
        for n, eng in enumerate(engines): info[f'engine{n}'] = eng
        config.append(info)
        print(f"Unknown git repo: {f}, found {len(engines)} executable")
  engine_list = []
  updated_config = [] # update the presence of engine in config
  for item in config:
    if item['dir'] is None or item['dir'][len('engines/'):] in f_list:
      updated_config.append(item)
      if item['engine'] is not None:
        print(f"loading {item['engine']}...            \r", end='')
        call_result = call_engine(item['engine'])
        if call_result is None:
          print(f"ERROR: unable to load '{item['engine']}', skipped.")
          continue
        name, version = call_result
        engine_info[item['engine']] = {
          'name': item['dir'][8:] if item['dir'] is not None else None,
          'version': 'unknown',
          'elo':   0,
          'score': 0,
          'win':   0,
          'lose':  0,
          'draw':  0
        }
        engine_info[item['engine']]['name'] = name
        engine_info[item['engine']]['version'] = version
        engine_list.append(item['engine'])
  config = updated_config[:]
  # print(json.dumps(engine_list,indent=2))
  # print(json.dumps(engine_info,indent=2))
  open("config.json","w").write(json.dumps(config, indent=2))
  if len(engine_list) < 2:
    print("ERROR: No engine found, match is not possible.")
    exit()

  pink     = (190, 140, 140)
  mint     = (53,101,84)
  gold     = (200,125,50)
  pink_red = (195, 72, 72)
  brown    = (161,61,45)
  purple   = (205,150,205)
  # TODO: tc is packed into tuple like (1, 0) which means 1+0
  tournament = [("/1:0",pink)]+ [("/3:0",mint), ("/5:0",brown)]
  os.system("mkdir result")
  for tc,color in tournament:
    tournament_date = time.strftime('%Y%m%d')
    pgn_file = f'{tc[1]}-0_{tournament_date}.pgn'
    os.system(f"rm result/{pgn_file} result/games.pgn")
    game_count = 0
    match_retry_count = 0
    match_retry_limit = 2
    engine_pairs = []
    # TODO: some sort of UI to select engine that will be matched
    # engine_list = engine_list[:2]
    # engine_list.pop(0)
    # engine_list.pop(3)
    # engine_list.pop(3)
    # engine_list.pop(1)
    # engine_list.pop(-2)
    # engine_list.pop(-1)
    for i in engine_list:
      for j in engine_list:
        if i != j: engine_pairs.append((i,j))
    game_total = len(engine_pairs)
    for engine1, engine2 in sample(engine_pairs, len(engine_pairs)):
      game_count += 1
      while match_retry_count <= match_retry_limit:
        result = match_handle((game_count, game_total, color), engine_info, engine1, engine2, tc)
        if result is not None: break
        match_retry_count += 1
      if match_retry_count > 0:
        print(f"INFO: match ended after {match_retry_count-1}/{match_retry_limit}(max) retry")
      if result is None:
        print(f"INFO: null result received, exiting...")
        terminate(ffmpeg)
        exit()
      engine_info[engine1]['score'] += result[0]
      engine_info[engine2]['score'] += result[1]
      new_elo1 = update_elo(engine_info[engine1]['elo'], engine_info[engine2]['elo'], result[0])
      new_elo2 = update_elo(engine_info[engine2]['elo'], engine_info[engine1]['elo'], result[1])
      print(engine_info[engine1]['elo'], new_elo1)
      print(engine_info[engine2]['elo'], new_elo2)
      engine_info[engine1]['elo'] = new_elo1
      engine_info[engine2]['elo'] = new_elo2
      if result[0] == 1:
        engine_info[engine1]['win'] += 1
        engine_info[engine2]['lose'] += 1
      elif result[1] == 1:
        engine_info[engine2]['win'] += 1
        engine_info[engine1]['lose'] += 1
      else:
        engine_info[engine1]['draw'] += 1
        engine_info[engine2]['draw'] += 1
    # saving result
    engine_info = dict(sorted(engine_info.items(), key=lambda x: x[1]['score'], reverse=True))
    player_list = []
    score_list  = []
    elo_list    = []
    winr_list   = []
    for engine in engine_info:
      name = engine_info[engine]['name']
      version = engine_info[engine]['version']
      score = engine_info[engine]['score']
      elo = engine_info[engine]['elo']
      win = engine_info[engine]['win']
      lose = engine_info[engine]['lose']
      draw = engine_info[engine]['draw']
      total = win + lose + draw
      engine_info[engine]['score'] = 0 # reset score
      player_list.append(f"{name} {version}")
      score_list.append(str(score))
      elo_list.append(str(elo))
      winr_list.append('N/A' if total == 0 else f"{win/total*100}%")
    header = ('Player', 'Score', 'ELO', 'Winrate')
    body = (
      tuple(player_list),
      tuple(score_list) ,
      tuple(elo_list)   ,
      tuple(winr_list)
    )
    table = get_table(header, body, True)
    with open("result/temp.txt", "w") as f:
      f.write(table + '\n\n')
    os.system(f"cat result/temp.txt result/games.pgn > result/{pgn_file}")
    os.system("rm result/temp.txt result/games.pgn")
    
    # ending page after tournament showing the result
    bg_color = color_accent(color, "pastel")
    fill_color = color_accent(color , "superlight")
    frame = Image.new("RGB", resolution, bg_color)
    d = ImageDraw.Draw(frame)
    result_draw_margin = 180
    tc_split = tc[1:].split(":")
    d.text((600,80), f"Tournament result: ({tc_split[0]}+{tc_split[1]})", font=get_font("bold", 56), fill=color_accent(color , "dark"))
    d.text((1100,950), f"Next tournament will begin shortly", font=get_font("default", 42), fill=color_accent(color , "dark"))
    d.rectangle((result_draw_margin, result_draw_margin, resolution[0]-result_draw_margin, resolution[1]-result_draw_margin), fill=fill_color)
    d.rectangle((result_draw_margin, result_draw_margin, resolution[0]-result_draw_margin, resolution[1]-result_draw_margin), width=3, outline=(20,)*3)
    standing = dict(sorted({i:engine_info[i]['score'] for i in engine_info}.items(), key=lambda item: item[1], reverse=True))
    ending_page = -1   # start with index zero below
    ending_page_timer = None
    ending_show_timer = Timer()
    frame_timer = Timer()
    while not ending_show_timer.check(5*60*1000):
      if ending_page_timer is None or ending_page_timer.check(15*1000):
        ending_page = (ending_page + 1) % -(len(engine_info.keys())//-10)
        d.rectangle((result_draw_margin, result_draw_margin, resolution[0]-result_draw_margin, resolution[1]-result_draw_margin), fill=fill_color)
        d.rectangle((result_draw_margin, result_draw_margin, resolution[0]-result_draw_margin, resolution[1]-result_draw_margin), width=3, outline=(20,)*3)
        for n,i in list(enumerate(standing))[10*ending_page:10*ending_page+10]:
          n -= 10*ending_page
          d.text((result_draw_margin+50, result_draw_margin+50+65*n), str(n+10*ending_page+1)+'.', font=get_font("light", 36), fill="grey")
          d.text((result_draw_margin+50+70, result_draw_margin+55+65*n), engine_info[i]['name'], font=get_font("default", 42), fill="black")
          d.text((result_draw_margin+50+70+500, result_draw_margin+60+65*n), engine_info[i]['version'], font=get_font("default", 36), fill=(70,70,70)) # not the best implementation, maybe use standing instead
          if standing[i] == 0.5:     d.text((result_draw_margin+50+70+1200, result_draw_margin+55+65*n), '½', font=get_font("default", 42), fill="black")
          elif standing[i]%1 == 0.5: d.text((result_draw_margin+50+70+1200, result_draw_margin+55+65*n), str(int(standing[i]//1))+'½', font=get_font("default", 42), fill="black")
          else:                      d.text((result_draw_margin+50+70+1200, result_draw_margin+55+65*n), str(int(standing[i])), font=get_font("default", 42), fill="black")
        if ending_page_timer is None:
          ending_page_timer = Timer()
        else:
          ending_page_timer.reset()
      if frame_timer.check(1/framerate):
        data = io.BytesIO()
        frame.save(data, format='JPEG')
        send_frame(data.getvalue())
        frame_timer.reset()

# TODO: move highlighting??
# TODO: maybe support weird engine output by being able to identify move notation
if __name__ == "__main__":
  try:
    main()
  except Exception as e:
    # print(json.dumps(str(globals()), indent=2))
    # print('\n\n\n')
    # print(json.dumps(str(dir()), indent=2))
    print(traceback.format_exc(), file=sys.stderr)
  terminate(ffmpeg)
