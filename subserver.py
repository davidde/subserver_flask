from flask import Flask, flash, make_response, render_template, request
from werkzeug.utils import secure_filename

from datetime import timedelta

import os
import re
import sys

import chardet


app = Flask(__name__)
app.secret_key = 'hoQf4^(xlos6@,mc/AfkoY7!p{;dLgd vfV1etvSu6*JcqzP'

def allowed_file(file):
    """
    Check if the Flask file isn't too large,
    see if its extension is valid, and return bool.
    """
    pos = file.tell()  # Save the current position
    file.seek(0, 2)    # Seek to the end of the file
    length = file.tell()  # The current position is the length
    file.seek(pos)     # Return to the saved position
    # print(file.tell())
    # print(length)
    if length > 150000:   # >150kB is too large
        return False

    filename = file.filename
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ['srt', 'vtt']

def string_content(file):
    """Returns the contents of the Flask file as string."""
    # "file.stream.read()" returns bytes, ".decode("utf-8")" converts them
    # to an "utf-8" encoded string; however not every file is in unicode.

    # We need a way of determining the character encoding;
    # the flask file object does not have this functionality.
    # Try-except is not useful either because a stream only returns data once.
    # This means a second read (in except clause) would be empty ...
    # -> We need chardet to detect the encoding of the file!
    file_contents = file.stream.read()

    result = chardet.detect(file_contents)
    enc = result['encoding']
    # print('\n\n' + str(enc) + '\n\n')
    if not enc:
        # When chardet can't detect the character encoding, which will happen
        # for non-text files, enc will be None. In this case we return None,
        # and handle it in the caller.
        return None
    else:
        file_contents = file_contents.decode(enc, errors='replace')

    return file_contents

@app.route('/')
def home():
    return render_template('home.html')

@app.route('/convert', methods=['POST'])
def upload_convert():
    # import pdb; pdb.set_trace()
    file = request.files.get('subtitlefile')
    if not file:
        flash('No file is selected.')
        return home()

    plusmin = float(request.form.get('plusmin'))
    seconds = request.form.get('seconds')
    if not seconds:
        flash('No seconds are entered.')
        return home()
    seconds = float(seconds)
    seconds *= plusmin

    if not allowed_file(file):
        flash('Select either an .srt or .vtt file.')
        return home()

    else:
        inputfile = secure_filename(file.filename)
        from_ext = inputfile.rsplit('.', 1)[1].lower()
        to_ext = request.form.get('to')
        if not to_ext in ['srt', 'vtt']:
            flash('Only converting to .srt or .vtt is supported.')
            return home()

        change_ext = False
        if from_ext != to_ext:
            change_ext = True
        outputfile = name_output(inputfile, seconds, change_ext)

        string_contents = string_content(file)
        if not string_contents:
            flash('Unknown character encoding. Only select valid subtitle files.')
            return home()
        elif inputfile.endswith('.srt'):
            result = convert_srt(string_contents, seconds, change_ext)
        else:
            result = convert_vtt(string_contents, seconds, change_ext)
        response = make_response(result)

        response_str = 'attachment; filename={}'.format(outputfile)
        response.headers['Content-Disposition'] = response_str
        return response


def name_output(inputfile, seconds, change_ext):
    """
    Determines the name of the outputfile based on the inputfile and seconds;
    the name of the new file is identical to the old one, but prepended with '{+x.xx_Sec}_'.
    
    However, if the file has already been processed by submod before, we simply change
    the 'increment number' x, instead of prepending '{+x.xx_Sec}_' a second time.
    This way we can conveniently process files multiple times, and still have sensible names.
    
    """
    # import pdb; pdb.set_trace()
    # Regex to check if the inputfile was previously processed by submod
    proc_regex = '\{[+-]\d+\.\d+_Sec\}_'
    proc = re.compile(proc_regex)
    processed = proc.match(inputfile)
    
    # The inputfile prefix as a string format
    input_prefix = '{{{0:.2f}_Sec}}_'
    
    # inputfile was processed by submod previously
    if processed:
        
        # Regex for extracting the increment number from the inputfile:
        number = re.compile('[+-]\d+\.\d+')
        match = number.search(inputfile)
        
        incr = float(match.group())
        incr += seconds
        
        # Prepare a placeholder for string formatting;
        # in the string 'inputfile', the first occurrence of the 'proc_regex' pattern
        # is substituted with the 'input_prefix' string.        
        placeholder = re.sub(proc_regex, input_prefix, inputfile, 1)
    
    # the inputfile has not been processed by submod before    
    else:
        incr = seconds
        placeholder = input_prefix + inputfile
        
    if incr >= 0:
        placeholder = '{{+' + placeholder[2:]
           
    # Determine the name of the outputfile by replacing
    # the increment number with the new one:
    outputfile = placeholder.format(incr)

    if change_ext:
        if outputfile.endswith('.srt'):
            outputfile = outputfile.rsplit('.', 1)[0] + '.vtt'
        else:
            outputfile = outputfile.rsplit('.', 1)[0] + '.srt'
    
    return outputfile


def convert_srt(file_contents, seconds, change_ext):
    """
    Loops through the given inputfile, modifies the lines consisting of the time encoding,
    and writes everything back to the 'new_content' string.
    
    This function is identical to convert_vtt,
    except that it uses ',' for the seconds field's decimal space.
    
    The subtitle files consist of a repetition of the following 3 lines:
    
    - Index-line: integer count indicating line number
    - Time-line: encoding the duration for which the subtitle appears
    - Sub-line: the actual subtitle to appear on-screen (1 or 2 lines)
    
    Example .srt (Note: ',' for decimal spaces):
    
    1
    00:00:00,243 --> 00:00:02,110
    Previously on ...
    
    2
    00:00:03,802 --> 00:00:05,314
    Etc.
    
    """
    # import pdb; pdb.set_trace()
    content_list = []
    skip = False
    time_line = re.compile('\d\d:\d\d:\d\d,\d\d\d')

    for line in file_contents.splitlines(True):
        # Time-line: This is the line we need to modify
        if time_line.match(line):
            # We need '.' instead of ',' for floats!
            line = line.replace(',', '.')
            new_line = process_line(line, seconds)
            if new_line == '(DELETED)\n\n':
                skip = True
            elif not change_ext:
                # Convert back to '.srt' style:
                new_line = new_line.replace('.', ',')
                
        else:
            # When skip = True, subtitles are shifted too far back into the past,
            # (before the start of the movie), so they are deleted:
            if skip == True:
                # Subtitles can be 1 or 2 lines; only turn of skip on empty line:
                if line == '\n' or line == '\r\n':
                    skip = False
                continue
            
            # All other lines are simply copied:
            else:
                new_line = line

        content_list.append(new_line)

    new_content = ''.join(content_list)

    return new_content


def convert_vtt(file_contents, seconds, change_ext):
    # import pdb; pdb.set_trace()
    content_list = []
    skip = False
    time_line = re.compile('\d\d:\d\d:\d\d.\d\d\d')

    for line in file_contents.splitlines(True):
        # Time-line: This is the line we need to modify
        if time_line.match(line):
            new_line = process_line(line, seconds)
            if new_line == '(DELETED)\n\n':
                skip = True
            elif change_ext:
                new_line = new_line.replace('.', ',')

        else:
            # When skip = True, subtitles are shifted too far back into the past,
            # (before the start of the movie), so they are deleted:
            if skip == True:
                # Subtitles can be 1 or 2 lines; only turn of skip on empty line:
                if line == '\n' or line == '\r\n':
                    skip = False
                continue
            
            # All other lines are simply copied:
            else:
                new_line = line

        content_list.append(new_line)

    new_content = ''.join(content_list)

    return new_content


def process_line(line, seconds):
    """
    Process the given line by adding seconds to start and end time.
    (subtracting if seconds is negative)
    
    Example line:  '00:00:01.913 --> 00:00:04.328'
    Index:          01234567890123456789012345678
    Index by tens: (0)        10        20     (28)

    """    
    start = line[0:12]
    start = process_time(start, seconds)
    
    end = line[17:29]
    end = process_time(end, seconds)
    
    if start == '(DELETED)\n\n':
        if end == '(DELETED)\n\n':
            line = '(DELETED)\n\n'
        else:
            line = '00:00:00.000 --> ' + end + '\n'
        
    else:        
        line = start + ' --> ' + end + '\n'
        
    return line

    
def process_time(time_string, incr):
    """
    Increment the given time_string by 'incr' seconds
    
    The time-string has the form '00:00:00.000',
    and converts to the following format string:
    '{0:02d}:{1:02d}:{2:06.3f}'
    
    """
    hrs  = int(time_string[0:2])
    mins = int(time_string[3:5])
    secs = float(time_string[6:12])
    
    time = timedelta(hours=hrs, minutes=mins, seconds=secs)
    incr = timedelta(seconds=incr)
    
    # incr can be negative, so the new time can be too:
    time = time + incr
    time = time.total_seconds()
    
    if time >= 0:
        # Since time is a float, hrs and mins need to be converted back to int for the string format
        hrs  = int(time // 3600)
        mins = int((time % 3600) // 60)
        secs = (time % 3600) % 60
    
        time_string = '{0:02d}:{1:02d}:{2:06.3f}'.format(hrs, mins, secs)
    
    else:
        # time < 0: the subtitles are now scheduled before the start of the movie,
        # so we can delete them
        time_string = '(DELETED)\n\n'
    
    return time_string


if __name__ == '__main__':
    app.run(port=5000, debug=True)