import pygame
import random

class Asteroid:
    def __init__(self, screen_width):
        self.radius = random.randint(15, 30)
        self.x = random.randint(self.radius, screen_width - self.radius)
        self.y = -self.radius
        self.speed = random.randint(3, 7)
        self.color = (100, 100, 100)
        self.rect = pygame.Rect(self.x - self.radius, self.y - self.radius, self.radius * 2, self.radius * 2)

    def update(self):
        self.y += self.speed
        self.rect.y = self.y - self.radius

    def draw(self, screen):
        pygame.draw.circle(screen, self.color, (int(self.x), int(self.y)), self.radius)
        # Ajouter un peu de détail pour faire "rocheux"
        pygame.draw.circle(screen, (80, 80, 80), (int(self.x) - 5, int(self.y) - 5), self.radius // 3)