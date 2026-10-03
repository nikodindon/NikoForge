import pygame

class Player:
    def __init__(self, screen_width, screen_height):
        self.screen_width = screen_width
        self.screen_height = screen_height
        self.width = 40
        self.height = 40
        self.x = screen_width // 2 - self.width // 2
        self.y = screen_height - 100
        self.speed = 7
        self.color = (0, 255, 0)  # Vert
        self.rect = pygame.Rect(self.x, self.y, self.width, self.height)

    def move(self, keys):
        if keys[pygame.K_LEFT] and self.x > 0:
            self.x -= self.speed
        if keys[pygame.K_RIGHT] and self.x < self.screen_width - self.width:
            self.x += self.speed
        if keys[pygame.K_UP] and self.y > 0:
            self.y -= self.speed
        if keys[pygame.K_DOWN] and self.y < self.screen_height - self.height:
            self.y += self.speed
        
        self.rect.x = self.x
        self.rect.y = self.y

    def draw(self, screen):
        # Dessiner un vaisseau simple (triangle)
        points = [
            (self.x + self.width // 2, self.y),
            (self.x + self.width, self.y + self.height),
            (self.x, self.y + self.height)
        ]
        pygame.draw.polygon(screen, self.color, points)
        # Petit moteur
        pygame.draw.rect(screen, (255, 100, 0), (self.x + 10, self.y + self.height, 20, 5))