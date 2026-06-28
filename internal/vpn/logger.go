package vpn

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

const maxLogSize = 1 * 1024 * 1024

type Logger struct {
	mu      sync.Mutex
	dir     string
	enabled bool
}

var Log *Logger

func InitLogger() {
	dir, err := os.UserConfigDir()
	if err != nil {
		dir = os.TempDir()
	}
	logDir := filepath.Join(dir, "free-vpn", "logs")
	os.MkdirAll(logDir, 0755)
	Log = &Logger{dir: logDir, enabled: true}
}

func (l *Logger) SetEnabled(on bool) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.enabled = on
}

func (l *Logger) Enabled() bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.enabled
}

func (l *Logger) Info(msg string) {
	l.write("INFO", msg)
}

func (l *Logger) Warn(msg string) {
	l.write("WARN", msg)
}

func (l *Logger) Error(msg string) {
	l.write("ERROR", msg)
}

func (l *Logger) write(level, msg string) {
	l.mu.Lock()
	defer l.mu.Unlock()

	if !l.enabled {
		return
	}

	now := time.Now()
	path := filepath.Join(l.dir, now.Format("2006-01-02")+".log")

	if fi, err := os.Stat(path); err == nil && fi.Size() > maxLogSize {
		rotate(path)
	}

	f, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return
	}
	defer f.Close()

	line := fmt.Sprintf("[%s] [%s] %s\n", now.Format("2006-01-02 15:04:05"), level, msg)
	f.WriteString(line)
}

func rotate(path string) {
	for i := 9; i > 0; i-- {
		old := fmt.Sprintf("%s.%d", path, i)
		older := fmt.Sprintf("%s.%d", path, i-1)
		os.Rename(older, old)
	}
	os.Rename(path, path+".1")
}
