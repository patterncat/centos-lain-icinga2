#!/usr/bin/python

import getopt
import sys
import urllib

STATE_OK = 0
STATE_WARNING = 1
STATE_CRITICAL = 2
STATE_UNKNOWN = 3
STATE_DEPENDENT = 4

def usage():
    _usage = '''
Usage:
        check_graphite_data <options>
Options:
        -c <num> --crit=<num>           Critical threshold
        -w <num> --warn=<num>           Warning threshold
        -u <url> --url=<url>            Graphite graph URL
        -s <secs> --seconds=<secs>      Average over the last N seconds of data
        --d1 <url> --d2 <url>           Diff the latest values between two graphs
        -W --holt-winters               Perform a Holt-Winters check
        -U --critupper                  Upper Holt-Winters band breach causes a crit,
                                        - breaching lower band causes a warn
        -L --critlower                  Lower Holt-Winters band breach causes a crit,
                                        - breaching upper band causes a warn
        (If -W, but neither -U nor -L are given, we will always warn)
        --scale=<multiplier>            scale, eg 8 to treat bytes as bits
        --scale-invert=<divisor>        scale, eg 1073741824 to treat bytes as GiB
                                        - --scale{-invert} lets you give thresholds in sane units
        -t                              type - Alert type: equal, notequal, less, greater(default)
'''
    print(_usage)


def pull_graphite_data(url):
    """Pull down raw data from Graphite"""
    # Make sure the url ends with '&rawData'
    if not url.endswith('&rawData'):
        url = url + '&rawData'

    # Catch URL errors
    try:
        data = urllib.urlopen(url).read()
        if len(data) == 0:
            print "Error: No data was returned. Did you specify an existing metric? - " + url
            sys.exit(STATE_UNKNOWN)
        return data
    except Exception,e:
        print "Error: "+ str(e) +" - " + url
        sys.exit(STATE_UNKNOWN)

def eval_graphite_data(data, seconds):
    """Get the most recent correct value from the data"""

    sample_period = int(data.split('|')[0].split(',')[-1])
    all_data_points = data.split('|')[-1].split(',')

    # Evaluate what graphite returned, should either be a float, or None
    # First, if the number of seconds of data we want to examine is smaller or
    # equals the graphite sample period, just grab the latest data point.
    # If that data point is None, grab the one before it.
    # If that is None too, return 0.0.
    if seconds <= sample_period:
        if not all_data_points[-1].startswith("None"):
            data_value = float(all_data_points[-1])
        elif not all_data_points[-2].startswith("None"):
            data_value = float(all_data_points[-2])
        else:
            data_value = 0.0
    else:
    # Second, if we requested more than on graphite sample period, work out how
    # many sample periods we wanted (python always rounds division *down*)
        data_points = (seconds/sample_period)
        data_set = [ float(x) for x in all_data_points[-data_points:]
                     if not x.startswith("None") ]
        if data_set:
            data_value = float( sum(data_set) / len(data_set) )
        else:
            data_value = 0.0
    return data_value


def get_hw_value(url, seconds=0):
    """Get the Holt-Winters value from a Graphite graph"""

    data = pull_graphite_data(url)
    for line in data.split():
        if line.startswith('holtWintersConfidenceUpper'):
            graphite_upper = eval_graphite_data(line, seconds)
        elif line.startswith('holtWintersConfidenceLower'):
            graphite_lower = eval_graphite_data(line, seconds)
        else:
            graphite_data = eval_graphite_data(line, seconds)

    return graphite_data, graphite_lower, graphite_upper


def get_value(url, seconds=0):
    """Get the value from a Graphite graph"""

    data = pull_graphite_data(url)
    data_value = eval_graphite_data(data, seconds)
    return data_value


def main(argv):
    try:
        opts, args = getopt.getopt(argv, 'hWULt:u:c:w:s:',
                ['help', 'holt-winters', 'critupper',
                    'critlower', 'type=', 'url=', 'crit=', 'warn=',
                    'seconds=', 'd1=', 'd2=',
                    'scale=' ,'scale-invert=']
                )
    except getopt.GetoptError, err:
        print str(err)
        sys.exit(STATE_UNKNOWN)

    url = None
    warn = None
    crit = None
    seconds = 0
    diff1 = None
    diff2 = None
    check_type = None
    hw = None
    critupper = None
    critlower = None
    scale = 1
    for opt, arg in opts:
        if opt in ('-h', '--help'):
            usage()
            sys.exit()
        elif opt in ('-u', '--url'):
            url = arg
        elif opt in ('-w', '--warn'):
            warn = float(arg)
        elif opt in ('-c', '--crit'):
            crit = float(arg)
        elif opt in ('-s', '--seconds'):
            seconds = int(arg)
        elif opt in ('-t', '--type'):
            check_type = arg
        elif opt in ('--d1'):
            diff1 = arg
        elif opt in ('--d2'):
            diff2 = arg
        elif opt in ('-W', '--holtwinters'):
            hw = True
        elif opt in ('-U', '--critupper'):
            critupper = True
        elif opt in ('-L', '--critlower'):
            critlower = True
        elif opt in ('--scale'):
            scale = float(arg)
        elif opt in ('--scale-invert'):
            scale = 1 / float(arg)
    if not hw and ((url == None) or (warn == None) or (crit == None)) \
            and not diff1 and not diff2:
        usage()
        sys.exit(STATE_UNKNOWN)

    if (diff1 == None and diff2 != None) or (diff1 != None and diff2 == None):
        usage()
        sys.exit(STATE_UNKNOWN)

    if hw:
        graphite_data, graphite_lower, graphite_upper = get_hw_value(url, seconds)
        print 'Current value: %s, lower band: %s, upper band: %s' % \
               (graphite_data, graphite_lower, graphite_upper)
        if (graphite_data > graphite_upper) or (graphite_data < graphite_lower):
            if critupper or critlower:
                sys.exit(STATE_CRITICAL)
            else:
                sys.exit(STATE_WARNING)
        else:
            sys.exit(STATE_OK)
    elif diff1 or diff2:
        graphite_data1 = get_value(diff1, seconds)
        graphite_data2 = get_value(diff2, seconds)
        graphite_data = abs(graphite_data1 - graphite_data2)
    else:
        graphite_data = get_value(url, seconds)
    graphite_data *= scale

    print 'Current value: %s, warn threshold: %s, crit threshold: %s' % \
           (graphite_data, warn, crit)
    if check_type == 'less':
        if crit >= graphite_data:
            sys.exit(STATE_CRITICAL)
        elif warn >= graphite_data:
            sys.exit(STATE_WARNING)
        else:
            sys.exit(STATE_OK)
    elif check_type == 'equal':
        if graphite_data == crit:
            sys.exit(STATE_CRITICAL)
        elif graphite_data == warn:
            sys.exit(STATE_WARNING)
        else:
            sys.exit(STATE_OK)
    elif check_type == 'notequal':
        if graphite_data != crit:
            if graphite_data != warn:
                sys.exit(STATE_CRITICAL)
            else:
                sys.exit(STATE_WARNING)
        else:
            sys.exit(STATE_OK)
    else:
        if graphite_data >= crit:
            sys.exit(STATE_CRITICAL)
        elif graphite_data >= warn:
            sys.exit(STATE_WARNING)
        else:
            sys.exit(STATE_OK)


if __name__ == '__main__':
    main(sys.argv[1:])