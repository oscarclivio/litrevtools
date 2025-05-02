from datetime import date, datetime, timedelta
import traceback
import time

import sys


def clean_input(prompt):
    prompt_parts = prompt.split('\n')
    for part in prompt_parts[:-1]:
        print(part)
    return input(prompt_parts[-1])

def yes_or_no(question):
    """Simple Yes/No Function."""
    prompt = f'{question} (y/n): '
    answer = clean_input(prompt).strip().lower()
    if answer not in ['y', 'n']:
        print(f'{answer} is invalid, please try again...')
        return yes_or_no(question)
    if answer == 'y':
        return True
    return False
    
def try_multiple_times(func, *args, trials=100, time_wait=10, **kwargs):
    trials_here = trials
    while trials_here > 0:
        try:
            return func(*args, **kwargs)
        except KeyboardInterrupt:
            traceback.print_exc()
            sys.exit()
        except Exception:
            trials_here -= 1
            if trials_here == 0:
                traceback.print_exc()
                raise f'^ The function could not be made to work after {trials} trials, stopping here.'
            else:
                time.sleep(time_wait)

# Function to calculate the number of days between a given date and today - authored by ChatGPT
def days_between(given_date_str):
    # Convert the given string date to a datetime object
    given_date = datetime.strptime(given_date_str, '%Y-%m-%d')
    
    # Get today's date
    today = datetime.today()
    
    # Calculate the difference between today and the given date
    difference = today - given_date
    
    # Return the difference in days
    return difference.days